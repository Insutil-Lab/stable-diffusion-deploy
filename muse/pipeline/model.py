import typing
from pathlib import Path
from typing import Any, List

import numpy as np
import torch
from PIL import Image
from pytorch_lightning import LightningModule


def load_model_from_config(config: Any, ckpt: str, verbose: bool = False) -> torch.nn.Module:
    from ldm.util import instantiate_from_config

    print(f"Loading model from {ckpt}")
    pl_sd = torch.load(ckpt, map_location="cpu")
    if "global_step" in pl_sd:
        print(f"Global Step: {pl_sd['global_step']}")
    sd = pl_sd["state_dict"]
    model = instantiate_from_config(config.model)
    m, u = model.load_state_dict(sd, strict=False)
    if len(m) > 0 and verbose:
        print("missing keys:")
        print(m)
    if len(u) > 0 and verbose:
        print("unexpected keys:")
        print(u)

    return model


class StableDiffusionModel(LightningModule):
    def __init__(self, model_path: Path, device: torch.device):
        from ldm.models.diffusion.ddim import DDIMSampler
        from omegaconf import OmegaConf

        super().__init__()

        config_path = model_path / "v1-inference.yml"
        weights_path = model_path / "sd-v1-4.ckpt"
        config = OmegaConf.load(f"{config_path}")
        config.model.params.cond_stage_config["params"] = {"device": device}
        self.model = load_model_from_config(config, f"{weights_path}")
        self.sampler = DDIMSampler(self.model)

    @typing.no_type_check
    def predict_step(
        self, prompts: List[str], batch_idx: int, height: int, width: int, num_inference_steps: int
    ) -> Any:
        batch_size = len(prompts)

        with self.model.ema_scope():
            uc = self.model.get_learned_conditioning(batch_size * [""])
            c = self.model.get_learned_conditioning(prompts)
            shape = [4, height // 8, width // 8]
            samples_ddim, _ = self.sampler.sample(
                S=num_inference_steps,
                conditioning=c,
                batch_size=batch_size,
                shape=shape,
                verbose=False,
                unconditional_guidance_scale=7.5,
                unconditional_conditioning=uc,
                eta=0.0,
                x_T=None,
            )

            x_samples_ddim = self.model.decode_first_stage(samples_ddim)
            x_samples_ddim = torch.clamp((x_samples_ddim + 1.0) / 2.0, min=0.0, max=1.0)
            x_samples_ddim = x_samples_ddim.cpu().permute(0, 2, 3, 1).numpy()

            x_samples_ddim = (255.0 * x_samples_ddim).astype(np.uint8)
            pil_results = [Image.fromarray(x_sample) for x_sample in x_samples_ddim]

        return pil_results
