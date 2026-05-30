"""
消字号合规预审引擎 — F5 输出模板模块。

定义 S1-S7 各状态的固定输出模板，主模型仅负责填充占位符。
配合 template_validator 校验输出结构完整性。

使用方式：
  from output_templates.template_definitions import get_template, build_s4_output
  from output_templates.template_validator import validate_output
"""
