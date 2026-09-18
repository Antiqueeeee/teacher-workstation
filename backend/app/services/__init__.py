"""业务规则层。

这一层**不得 import FastAPI** —— 保证统计口径与业务规则可以脱离 HTTP 单独单测
（见 CONTRIBUTING.md §2）。
"""
