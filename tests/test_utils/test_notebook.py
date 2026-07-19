# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.utils.notebook import is_notebook_env, patch_str_none_type, setup_notebook

def test_is_notebook_env_defaults_false():
    assert is_notebook_env() is False

def test_patch_str_none_type():
    if sys.version_info < (3, 10):
        patch_str_none_type()
    assert True
