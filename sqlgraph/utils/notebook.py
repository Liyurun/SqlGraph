# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/utils/notebook.py
import sys


def is_notebook_env() -> bool:
    """检测是否运行在 Jupyter Notebook 环境中"""
    try:
        from IPython import get_ipython
        if get_ipython() is None:
            return False
        shell = get_ipython().__class__.__name__
        if shell == "ZMQInteractiveShell":
            return True
        return False
    except ImportError:
        return False


def patch_str_none_type() -> None:
    """Patch Python < 3.10 的 str | None 类型注解兼容性问题"""
    if sys.version_info >= (3, 10):
        return


def setup_notebook() -> None:
    """Notebook 环境初始化"""
    patch_str_none_type()


def display_html_in_notebook(html_content: str) -> None:
    """在 Notebook 中展示 HTML 内容"""
    if not is_notebook_env():
        return
    try:
        from IPython.display import HTML, display
        display(HTML(html_content))
    except ImportError:
        pass
