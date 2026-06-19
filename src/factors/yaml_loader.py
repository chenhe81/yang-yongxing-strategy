"""YAML策略配置加载 — 将YAML转为Task对象"""
import yaml
from src.factors.engine import Task


def task_from_yaml(path: str) -> Task:
    """读取YAML策略配置，返回Task对象"""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    valid_fields = Task.__dataclass_fields__
    kwargs = {}
    for k, v in cfg.items():
        if k in valid_fields:
            # 处理布尔值字符串
            if isinstance(v, str) and v.lower() in ("true", "false"):
                v = v.lower() == "true"
            kwargs[k] = v
    return Task(**kwargs)
