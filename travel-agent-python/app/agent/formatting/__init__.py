"""行程输出落地（format_output）的各阶段实现。

workflow.format_output 只做编排；本包按职责分三块：
- facts：候选快照命中后的权威字段回填与溯源标注；
- prices：酒店/餐饮定价链（联网实时价 → 基准价×季节系数）与预算重算；
- quality：成品行程的终检、降级原因汇总与质量结论。
"""
