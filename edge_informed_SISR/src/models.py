import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader
from .components import SRGenerator, EdgeGenerator, GradientGenerator, Discriminator
from .dataset import Dataset
from .loss import AdversarialLoss, ContentLoss, StyleLoss


class BaseModel(nn.Module):
    def __init__(self, name, config):
        super().__init__()

        self.name = name
        self.config = config
        self.iteration = 0

        self.gen_weights_path = os.path.join(config.PATH, name+"_gen.pth")
        self.dis_weights_path = os.path.join(config.PATH, name+"_dis.pth")

    def load(self):
        if os.path.exists(self.gen_weights_path):
            print("Loading generator...{}".format(self.name))

            if torch.cuda.is_available():
                data = torch.load(self.gen_weights_path)
            else:
                data = torch.load(self.gen_weights_path, map_location = lambda storage, loc:storage)

            self.generator.load_state_dict(data["generator"])
            self.iteration = data["iteration"]

        # load discriminator only when training
        if self.config.MODE == 1 and os.path.exists(self.dis_weights_path):
            print("loading discriminator...{}".format(self.name))
            
            if torch.cuda.is_available():
                data = torch.load(self.dis_weights_path)
            else:
                data = torch.load(self.dis_weights_path, map_location = lambda storage, loc:storage)

            self.discriminator.load_state_dict(data["discriminator"])

    def save(self):
        print("Saving...{}...".format(self.name))

        torch.save({
            "iteration": self.iteration,
            "generator": self.generator.state_dict()
            }, self.gen_weights_path)

        torch.save({
            "discriminator": self.discriminator.state_dict()
            }, self.dis_weights_path)

class EdgeModel(BaseModel):
    def __init__(self, config):
        super().__init__("EdgeModel", config)

        self.config = config
        # generator input: [rgb(3) + edge(1)]
        # discriminator input: (rgb(3) + edge(1))
        self.generator = EdgeGenerator()
        self.discriminator = Discriminator(in_channels = 4, use_sigmoid = config.GAN_LOSS != "hinge")

        if len(config.GPU) > 1:
            self.generator = nn.DataParallel(self.generator, config.GPU)
            self.discriminator = nn.DataParallel(self.discriminator, config.GPU)

        self.L1_loss = nn.L1Loss()
        self.adversarial_loss = AdversarialLoss(type = config.GAN_LOSS)

        self.add_module('generator', self.generator)
        self.add_module('discriminator', self.discriminator)

        self.add_module("L1_loss", self.L1_loss)
        self.add_module("adversarial_loss", self.adversarial_loss)

        self.gen_optimizer = optim.Adam(
            params = self.generator.parameters(),
            lr = float(config.LR),
            betas = (config.BETA1, config.BETA2)
            )

        self.dis_optimizer = optim.Adam(
            params = self.discriminator.parameters(),
            lr = float(config.LR),
            betas = (config.BETA1, config.BETA2)
            )

    def forward(self, lr_images, lr_edges):
        hr_images = F.interpolate(lr_images, scale_factor = self.config.SCALE)
        hr_edges = F.interpolate(lr_edges, scale_factor = self.config.SCALE)
        inputs = torch.cat((hr_images, hr_edges), dim = 1)
        outputs = self.generator.forward(inputs)
        return outputs
    
    def backward(self, gen_loss, dis_loss):
        dis_loss.backward()
        self.dis_optimizer.step()

        gen_loss.backward()
        self.gen_optimizer.step()

    def process(self, lr_images, hr_images, lr_edges, hr_edges):
        self.iteration += 1

        #zero optimizers
        self.gen_optimizer.zero_grad()
        self.dis_optimizer.zero_grad()

        #process outputs
        outputs = self.forward(lr_images, lr_edges)
        gen_loss = 0
        dis_loss = 0

        #discriminator loss
        dis_input_real = torch.cat((hr_images, hr_edges), dim=1)
        dis_input_fake = torch.cat((hr_images, outputs.detach()), dim=1)
        dis_real, dis_real_feat = self.discriminator.forward(dis_input_real)        # in: (rgb(3) + edge(1))
        dis_fake, dis_fake_feat = self.discriminator.forward(dis_input_fake)        # in: (rgb(3) + edge(1))
        dis_real_loss = self.adversarial_loss(dis_real, True, True)
        dis_fake_loss = self.adversarial_loss(dis_fake, False, True)
        dis_loss += (dis_real_loss + dis_fake_loss) / 2

        # generator adversarial loss
        gen_input_fake = torch.cat((hr_images, outputs), dim=1)
        gen_fake, gen_fake_feat = self.discriminator.forward(gen_input_fake)        # in: (rgb(3) + edge(1))
        gen_gan_loss = self.adversarial_loss(gen_fake, True, False) * self.config.ADV_LOSS_WEIGHT1
        gen_loss += gen_gan_loss

        # generator feature matching loss
        gen_fm_loss = 0 
        for i in range(len(dis_real_feat)):
            gen_fm_loss += self.L1_loss(gen_fake_feat[i], dis_real_feat[i].detach())
        gen_fm_loss = gen_fm_loss * self.config.FM_LOSS_WEIGHT
        gen_loss += gen_fm_loss

        # create logs
        logs = [
            ("l_dis", dis_loss.item()),
            ("l_gen", gen_gan_loss.item()),
            ("l_fm", gen_fm_loss.item()),
        ]

        return outputs, gen_loss, dis_loss, logs

class SRModel(BaseModel):
    def __init__(self, config):
        super().__init__("SRModel", config)

        self.config = config
        # generator input: [rgb(3) + edge(1)]
        # discriminator input: (rgb(3) 
        self.generator = SRGenerator()
        self.discriminator = Discriminator(in_channels = 3, use_sigmoid = config.GAN_LOSS != "hinge")

        if len(config.GPU) > 1:
            self.generator = nn.DataParallel(self.generator, config.GPU)
            self.discriminator = nn.DataParallel(self.discriminator, config.GPU)

        self.L1_loss = nn.L1Loss()
        self.content_loss = ContentLoss()
        self.style_loss = StyleLoss()
        self.adversarial_loss = AdversarialLoss(type = config.GAN_LOSS)

        kernel = np.zeros((self.config.SCALE, self.config.SCALE))
        kernel[0,0] = 1
        kernel_weight = torch.tensor(np.tile(kernel, (3, 1, 1, 1))).float()

        #self.scale_kernel = kernel_weight
        self.register_buffer('scale_kernel', kernel_weight)

        self.add_module('generator', self.generator)
        self.add_module('discriminator', self.discriminator)

        self.add_module("L1_loss", self.L1_loss)
        self.add_module("content_loss", self.content_loss)
        self.add_module("style_loss", self.style_loss)
        self.add_module("adversarial_loss", self.adversarial_loss)

        self.gen_optimizer = optim.Adam(
            params = self.generator.parameters(),
            lr = float(config.LR),
            betas = (config.BETA1, config.BETA2)
            )

        self.dis_optimizer = optim.Adam(
            params = self.discriminator.parameters(),
            lr = float(config.LR),
            betas = (config.BETA1, config.BETA2)
            )

    def forward(self, lr_images, hr_edges):
        hr_images = F.conv_transpose2d(lr_images, self.scale_kernel, padding=0, stride=self.config.SCALE, groups=3)
        inputs = torch.cat((hr_images, hr_edges), dim=1)
        outputs = self.generator.forward(inputs)
        return outputs

    def backward(self, gen_loss, dis_loss):
        dis_loss.backward()
        self.dis_optimizer.step()

        gen_loss.backward()
        self.gen_optimizer.step()

    def process(self, lr_images, hr_images, lr_edges, hr_edges):
        self.iteration += 1

        # zero optimizers
        self.gen_optimizer.zero_grad()
        self.dis_optimizer.zero_grad()

        # process outputs
        outputs = self.forward(lr_images, hr_edges)
        gen_loss = 0
        dis_loss = 0

        #discriminator loss
        dis_input_real = hr_images
        dis_input_fake = outputs.detach()
        dis_real, _ = self.discriminator.forward(dis_input_real)                    # in: [rgb(3)]
        dis_fake, _ = self.discriminator.forward(dis_input_fake)                    # in: [rgb(3)]
        dis_real_loss = self.adversarial_loss(dis_real, True, True)
        dis_fake_loss = self.adversarial_loss(dis_fake, False, True)
        dis_loss += (dis_real_loss + dis_fake_loss) / 2


        # generator adversarial loss
        gen_input_fake = outputs
        gen_fake, _ = self.discriminator.forward(gen_input_fake)                    # in: [rgb(3)]
        gen_gan_loss = self.adversarial_loss(gen_fake, True, False) * self.config.ADV_LOSS_WEIGHT2
        gen_loss += gen_gan_loss


        # generator L1 loss
        gen_l1_loss = self.L1_loss(outputs, hr_images) * self.config.L1_LOSS_WEIGHT
        gen_loss += gen_l1_loss


        # generator content loss
        gen_content_loss = self.content_loss(outputs, hr_images)
        gen_content_loss = gen_content_loss * self.config.CONTENT_LOSS_WEIGHT
        gen_loss += gen_content_loss


        # generator style loss
        gen_style_loss = self.style_loss(outputs, hr_images)
        gen_style_loss = gen_style_loss * self.config.STYLE_LOSS_WEIGHT
        gen_loss += gen_style_loss


        # create logs
        logs = [
            ("l_dis", dis_loss.item()),
            ("l_gen", gen_gan_loss.item()),
            ("l_l1", gen_l1_loss.item()),
            ("l_content", gen_content_loss.item()),
            ("l_style", gen_style_loss.item()),
            ]

        return outputs, gen_loss, dis_loss, logs

class GradientModel(BaseModel):
    def __init__(self, config):
        super().__init__("GradientModel", config)

        self.config = config
        # generator input: [rgb(3) + edge(1)]
        # discriminator input: (rgb(3) + edge(1))
        self.generator = GradientGenerator()
        self.discriminator = Discriminator(in_channels = 4, use_sigmoid = config.GAN_LOSS != "hinge")

        if len(config.GPU) > 1:
            self.generator = nn.DataParallel(self.generator, config.GPU)
            self.discriminator = nn.DataParallel(self.discriminator, config.GPU)

        self.L1_loss = nn.L1Loss()
        self.adversarial_loss = AdversarialLoss(type = config.GAN_LOSS)

        self.add_module('generator', self.generator)
        self.add_module('discriminator', self.discriminator)

        self.add_module("L1_loss", self.L1_loss)
        self.add_module("adversarial_loss", self.adversarial_loss)

        self.gen_optimizer = optim.Adam(
            params = self.generator.parameters(),
            lr = float(config.LR),
            betas = (config.BETA1, config.BETA2)
            )

        self.dis_optimizer = optim.Adam(
            params = self.discriminator.parameters(),
            lr = float(config.LR),
            betas = (config.BETA1, config.BETA2)
            )

    def forward(self, lr_images, lr_gradients):
        hr_images = F.interpolate(lr_images, scale_factor = self.config.SCALE)
        hr_gradients = F.interpolate(lr_gradients, scale_factor = self.config.SCALE)
        inputs = torch.cat((hr_images, hr_gradients), dim = 1)
        outputs = self.generator.forward(inputs)
        return outputs
    
    def backward(self, gen_loss, dis_loss):
        dis_loss.backward()
        self.dis_optimizer.step()

        gen_loss.backward()
        self.gen_optimizer.step()

    def process(self, lr_images, hr_images, lr_gradients, hr_gradients):
        self.iteration += 1

        #zero optimizers
        self.gen_optimizer.zero_grad()
        self.dis_optimizer.zero_grad()

        #process outputs
        outputs = self.forward(lr_images, lr_gradients)
        gen_loss = 0
        dis_loss = 0

        #discriminator loss
        dis_input_real = torch.cat((hr_images, hr_gradients), dim=1)
        dis_input_fake = torch.cat((hr_images, outputs.detach()), dim=1)
        dis_real, dis_real_feat = self.discriminator.forward(dis_input_real)        # in: (rgb(3) + edge(1))
        dis_fake, dis_fake_feat = self.discriminator.forward(dis_input_fake)        # in: (rgb(3) + edge(1))
        dis_real_loss = self.adversarial_loss(dis_real, True, True)
        dis_fake_loss = self.adversarial_loss(dis_fake, False, True)
        dis_loss += (dis_real_loss + dis_fake_loss) / 2

        # generator adversarial loss
        gen_input_fake = torch.cat((hr_images, outputs), dim=1)
        gen_fake, gen_fake_feat = self.discriminator.forward(gen_input_fake)        # in: (rgb(3) + edge(1))
        gen_gan_loss = self.adversarial_loss(gen_fake, True, False) * self.config.ADV_LOSS_WEIGHT1
        gen_loss += gen_gan_loss

        # generator feature matching loss
        gen_fm_loss = 0 
        for i in range(len(dis_real_feat)):
            gen_fm_loss += self.L1_loss(gen_fake_feat[i], dis_real_feat[i].detach())
        gen_fm_loss = gen_fm_loss * self.config.FM_LOSS_WEIGHT
        gen_loss += gen_fm_loss

        # create logs
        logs = [
            ("l_dis", dis_loss.item()),
            ("l_gen", gen_gan_loss.item()),
            ("l_fm", gen_fm_loss.item()),
        ]

        return outputs, gen_loss, dis_loss, logs