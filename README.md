# pumpcalc 泵站工况计算

纯 Python 标准库实现，比较同型泵串联/并联及变速运行方案。

## 用法

```
python -m pumpcalc CURVE.csv PLANS.json OUT.csv OUT.json
```

- `CURVE.csv`：单泵性能曲线，表头 `flow,head,efficiency`。流量(m3/s)从零严格递增，扬程(m)为正且严格递减，效率在 (0, 1]。
- `PLANS.json`：方案数组（或含 `plans` 键的对象）。每个方案含 `name`（唯一）、`pumps`（正整数）、`speed_ratio`（正）、`arrangement`（`series`/`parallel`）、`static_head`、`resistance`、`hours`（均非负）。
- 输出工况 CSV 与汇总 JSON：成功方案按输入功率再按名称升序，失败方案保留 `no_flow`/`out_of_range` 状态且数值为空。

## 计算规则

- 曲线分段线性插值，禁止外推；转速比 r 使流量乘 r、扬程乘 r²。
- 串联同流量叠加扬程，并联同扬程叠加流量；管路扬程 = 静扬程 + 阻力系数 × 总流量²。
- 静扬程不低于零流量组合扬程时报 `no_flow`，交点超出最大总流量时报 `out_of_range`。
- 效率按缩放前单泵流量插值；水力功率 ρgQH（ρ=1000，g=9.80665）除以效率得输入功率，乘小时数得千瓦时耗能。
- 输入非法时不产生任何输出文件。

## 示例与测试

```
python -m pumpcalc examples/curve.csv examples/plans.json out/results.csv out/summary.json
python -m unittest discover -s tests
```
