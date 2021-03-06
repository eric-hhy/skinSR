import os
import yaml

class Config(dict):
    def __init__(self, config_path):
        with open(config_path, "r") as configfile:
            self._yaml = configfile.read()
            self._dict = yaml.load(self._yaml)
            self._dict["PATH"] = os.path.dirname(config_path)

    def __getattr__(self, key):
        if self._dict.get(key) is not None:
            return self._dict[key]
        
        #if self.get(key) is not None:
            #return self.get(key)

        #if DEFAULT_CONFIG.get(key) is not None:
            #return DEFAULT_CONFIG[key]

        #return None

    def print(self):
        print('Model configurations:')
        print('---------------------------------')
        print(self._yaml)
        print('')
        print('---------------------------------')
        print('')

    DEFAULT_CONFIG = {
    'MODE': 1,                      # 1: train, 2: test, 3: eval
    'MODEL': 1,                     # 1: edge model, 2: SR model, 3: SR model with edge enhancer
    'SCALE': 4,                     # scale factor (2, 4, 8)
    'SEED': 10,                     # random seed
    'GPU': [0],                     # list of gpu ids
    'DEBUG': 0,                     # turns on debugging mode
    'VERBOSE': 0,                   # turns on verbose mode in the output console

    'LR': 0.0001,                   # learning rate
    'BETA1': 0.0,                   # adam optimizer beta1
    'BETA2': 0.9,                   # adam optimizer beta2
    'BATCH_SIZE': 8,                # input batch size for training
    'HR_SIZE': 256,                 # HR image size for training 0 for original size
    'SIGMA': 2,                     # standard deviation of the Gaussian filter used in Canny edge detector (0: random, -1: no edge)
    'MAX_ITERS': 2e7,               # maximum number of iterations to train the model
    'EDGE_THRESHOLD': 0.5,          # edge detection threshold

    'L1_LOSS_WEIGHT': 1,            # l1 loss weight
    'FM_LOSS_WEIGHT': 10,           # feature-matching loss weight
    'STYLE_LOSS_WEIGHT': 250,       # style loss weight
    'CONTENT_LOSS_WEIGHT': 0.1,     # content loss weight
    'ADV_LOSS_WEIGHT1': 0.1,        # edge model adversarial loss weight
    'ADV_LOSS_WEIGHT2': 1,          # SR model adversarial loss weight
    'GAN_LOSS': 'hinge',            # nsgan | lsgan | hinge
    'MGE_LOSS_WEIGHT': 0.1,         #mge loss weight

    'SAVE_INTERVAL': 1000,          # how many iterations to wait before saving model (0: never)
    'SAMPLE_INTERVAL': 1000,        # how many iterations to wait before sampling (0: never)
    'SAMPLE_SIZE': 12,              # number of images to sample
    'EVAL_INTERVAL': 0,             # how many iterations to wait before model evaluation (0: never)
    'LOG_INTERVAL': 10,             # how many iterations to wait before logging training status (0: never)
}