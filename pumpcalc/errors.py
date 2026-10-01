"""输入校验相关的异常定义。"""


class InputError(ValueError):
    """输入数据非法（缺失、非有限、违反单调性等）。"""
