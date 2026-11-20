"""结构化输入错误：错误码 + 字段位置（JSON Path 风格）。"""


class InputError(Exception):
    """所有可预期的输入错误都抛出本异常，由 CLI 统一转成 JSON。"""

    def __init__(self, code: str, field: str, message: str):
        super().__init__(message)
        self.code = code
        self.field = field
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "field": self.field, "message": self.message}


# 错误码约定（README 中有完整表格）：
E_MISSING = "E1001"      # 缺少必填字段
E_TYPE = "E1002"         # 类型不符
E_VALUE = "E1003"        # 取值越界 / 枚举非法
E_UNKNOWN = "E1004"      # 出现未声明字段
E_DUPLICATE = "E1005"    # ID 重复
E_REFERENCE = "E1006"    # 引用不存在
E_SEMANTIC = "E1007"     # 语义结构冲突
E_PARSE = "E2001"        # 文件 / JSON 解析失败
