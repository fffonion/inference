# Copyright 2022-2023 XProbe Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import collections.abc
import logging
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ...constants import XINFERENCE_CACHE_DIR
from ..core import CacheableModelSpec, ModelDescription
from ..utils import valid_model_revision
from .stable_diffusion.core import DiffusionModel

MAX_ATTEMPTS = 3

logger = logging.getLogger(__name__)

IMAGE_MODEL_DESCRIPTIONS: Dict[str, List[Dict]] = defaultdict(list)


def get_image_model_descriptions():
    import copy

    return copy.deepcopy(IMAGE_MODEL_DESCRIPTIONS)


class ImageModelFamilyV1(CacheableModelSpec):
    model_family: str
    model_name: str
    model_id: str
    model_revision: str
    model_hub: str = "huggingface"
    controlnet: Optional[List["ImageModelFamilyV1"]]


class ImageModelDescription(ModelDescription):
    def __init__(
        self,
        address: Optional[str],
        devices: Optional[List[str]],
        model_spec: ImageModelFamilyV1,
        model_path: Optional[str] = None,
    ):
        super().__init__(address, devices, model_path=model_path)
        self._model_spec = model_spec

    def to_dict(self):
        return {
            "model_type": "image",
            "address": self.address,
            "accelerators": self.devices,
            "model_name": self._model_spec.model_name,
            "model_family": self._model_spec.model_family,
            "model_revision": self._model_spec.model_revision,
            "controlnet": self._model_spec.controlnet,
        }

    def to_version_info(self):
        from .utils import get_model_version

        if self._model_path is None:
            is_cached = get_cache_status(self._model_spec)
            file_location = get_cache_dir(self._model_spec)
        else:
            is_cached = True
            file_location = self._model_path

        if self._model_spec.controlnet is None:
            return [
                {
                    "model_version": get_model_version(self._model_spec, None),
                    "model_file_location": file_location,
                    "cache_status": is_cached,
                    "controlnet": "zoe-depth",
                }
            ]
        else:
            res = []
            for cn in self._model_spec.controlnet:
                res.append(
                    {
                        "model_version": get_model_version(self._model_spec, cn),
                        "model_file_location": file_location,
                        "cache_status": is_cached,
                        "controlnet": cn.model_name,
                    }
                )
            return res


def generate_image_description(
    image_model: ImageModelFamilyV1,
) -> Dict[str, List[Dict]]:
    res = defaultdict(list)
    res[image_model.model_name].extend(
        ImageModelDescription(None, None, image_model).to_version_info()
    )
    return res


def match_diffusion(model_name: str) -> ImageModelFamilyV1:
    from ..utils import download_from_modelscope
    from . import BUILTIN_IMAGE_MODELS, MODELSCOPE_IMAGE_MODELS

    if download_from_modelscope():
        if model_name in MODELSCOPE_IMAGE_MODELS:
            logger.debug(f"Image model {model_name} found in ModelScope.")
            return MODELSCOPE_IMAGE_MODELS[model_name]
        else:
            logger.debug(
                f"Image model {model_name} not found in ModelScope, "
                f"now try to load it via builtin way."
            )

    if model_name in BUILTIN_IMAGE_MODELS:
        return BUILTIN_IMAGE_MODELS[model_name]
    else:
        raise ValueError(
            f"Image model {model_name} not found, available"
            f"model list: {BUILTIN_IMAGE_MODELS.keys()}"
        )


def cache(model_spec: ImageModelFamilyV1):
    from ..utils import cache

    return cache(model_spec, ImageModelDescription)


def get_cache_dir(model_spec: ImageModelFamilyV1):
    return os.path.realpath(os.path.join(XINFERENCE_CACHE_DIR, model_spec.model_name))


def get_cache_status(
    model_spec: ImageModelFamilyV1,
) -> bool:
    cache_dir = get_cache_dir(model_spec)
    meta_path = os.path.join(cache_dir, "__valid_download")
    return valid_model_revision(meta_path, model_spec.model_revision)


def create_image_model_instance(
    subpool_addr: str, devices: List[str], model_uid: str, model_name: str, **kwargs
) -> Tuple[DiffusionModel, ImageModelDescription]:
    model_spec = match_diffusion(model_name)
    controlnet = kwargs.get("controlnet")
    # Handle controlnet
    if controlnet is not None:
        if isinstance(controlnet, str):
            controlnet = [controlnet]
        elif not isinstance(controlnet, collections.abc.Sequence):
            raise ValueError("controlnet should be a str or a list of str.")
        elif set(controlnet) != len(controlnet):
            raise ValueError("controlnet should be a list of unique str.")
        elif not model_spec.controlnet:
            raise ValueError(f"Model {model_name} has empty controlnet list.")

        controlnet_model_paths = []
        assert model_spec.controlnet is not None
        for name in controlnet:
            for cn_model_spec in model_spec.controlnet:
                if cn_model_spec.model_name == name:
                    model_path = cache(cn_model_spec)
                    controlnet_model_paths.append(model_path)
                    break
            else:
                raise ValueError(
                    f"controlnet `{name}` is not supported for model `{model_name}`."
                )
        if len(controlnet_model_paths) == 1:
            kwargs["controlnet"] = controlnet_model_paths[0]
        else:
            kwargs["controlnet"] = controlnet_model_paths
    model_path = cache(model_spec)
    model = DiffusionModel(model_uid, model_path, **kwargs)
    model_description = ImageModelDescription(
        subpool_addr, devices, model_spec, model_path=model_path
    )
    return model, model_description
