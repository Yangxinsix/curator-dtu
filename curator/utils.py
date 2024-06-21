import torch
from e3nn.util.jit import script
from omegaconf import open_dict, OmegaConf, DictConfig
from hydra import compose, initialize
import hydra
from hydra.utils import instantiate
from collections import abc
import logging
from ase import units
from pathlib import Path
from typing import Optional

def register_resolvers():
    OmegaConf.register_new_resolver("multiply", lambda x, y: x * y)
    OmegaConf.register_new_resolver("divide", lambda x, y: x / y)
    OmegaConf.register_new_resolver("multiply_fs", lambda x: x * units.fs)
    OmegaConf.register_new_resolver("divide_by_fs", lambda x: x / units.fs)

def load_model(model_file, device):
    if model_file.suffix == '.pt':
        model = torch.jit.load(model_file, map_location=torch.device(device))
    else:
        model_dict = torch.load(model_file, map_location=torch.device(device))
        datamodule = instantiate(model_dict['data_params'])
        datamodule.setup()
        model = instantiate(model_dict['model_params'])
        model.initialize_modules(datamodule)
        model.load_state_dict(model_dict['model'])
    
    return model

def load_models(model_paths, device):
    if isinstance(model_paths, str):
        model_paths = [model_paths]
    
    models = []
    for model_path in model_paths:
        path = Path(model_path)
        if path.is_file() and (path.suffix == '.pt' or path.suffix == '.pth'):
            models.append(load_model(path, device))
    
    return models

class CustomFormatter(logging.Formatter):
    format = "%(asctime)s: %(message)s"
    time_format = "%Y-%m-%d %H:%M:%S"
     
    FORMATS = {
        logging.DEBUG: format,
        logging.INFO: "%(message)s",
        logging.WARNING: format,
        logging.ERROR: format,
        logging.CRITICAL: format
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, self.time_format)
        return formatter.format(record)

# Set up Early stopping for pytorch training 
class EarlyStopping():
    def __init__(self, patience=5, min_delta=0):

        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.early_stop = False

    def __call__(self, val_loss, best_loss):
        if val_loss - best_loss > self.min_delta:
            self.counter +=1
            if self.counter >= self.patience:  
                self.early_stop = True
        return self.early_stop

def deploy_model(model, file_path: str):
    compiled_model = script(model)
    compiled_model.save()

# Auxiliary function for parsing config file 
def get_all_pairs(d, keys=()):
    if isinstance(d, abc.Mapping):
         for k in d:
            for rv in get_all_pairs(d[k], keys + (k, )):
                yield rv
    else:
        yield (keys, d)

# Ugly workaround for specifying config files outside of the package
def read_user_config(filepath: Optional[str]=None, config_path="configs", config_name="train.yaml"):    
    # get override list
    override_list = []
    if filepath is not None:
        # load user defined config file
        user_cfg = OmegaConf.load(filepath)
        if "defaults" in user_cfg:
            default_list = user_cfg.pop("defaults")
            for d in default_list:
                for k, v in d.items():
                    override_list.append(f"{k}={v}")
        
        for k, v in get_all_pairs(user_cfg):
            key = ".".join(k)
            value = str(v).replace("'", "")
            if value == 'None':
                value = 'null'
            override_list.append(f'++{key}={value}')
    
    # reload hyperparameters         
    hydra.core.global_hydra.GlobalHydra.instance().clear()
    with initialize(version_base=None, config_path=config_path):
        cfg = compose(config_name=config_name, overrides=override_list)
    
    # Allow write access to unknown fields
    OmegaConf.set_struct(cfg, False)
        
    return cfg
