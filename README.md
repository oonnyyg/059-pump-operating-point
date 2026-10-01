# pumpcalc — 泵站工况计算

仅使用 Python 标准库，计算同型泵不同运行方案（泵数、串并联、转速比）与
管路特性曲线的工况交点，并比较输入功率与耗能。

单位统一为：米、立方米每秒、小时。

## 用法

```
python -m pumpcalc pump_curve.csv schemes.json out_points.csv out_summary.json
```

- 曲线 CSV 列：`flow_m3s,head_m,efficiency`（至少两点；流量从零严格递增；
  扬程严格递减且为正；`0 < efficiency <= 1`；禁止外推）。
- 方案 JSON：数组（或 `{"schemes": [...]}`），每项含
  `name`（唯一）、`pump_count`（正整数）、`connection`
  （`series`/`parallel`，默认并联）、`speed_ratio`（正）、
  `static_head_m`、`resistance_s2m5`、`hours`（其余非负）。

## 计算规则

- 分段线性插值；相似律：流量乘转速比，扬程乘转速比平方。
- 串联：同流量叠加扬程；并联：同扬程叠加流量。
- 管路扬程 `H = H_static + R * Q_total^2`。
- 静扬程不低于零流量组合扬程时状态为 `no_flow`；
  交点超出组合曲线最大总流量时状态为 `out_of_range`。
- 效率按缩放前单泵流量插值；水力功率 `rho*g*H*Q`
  （rho=1000，g=9.80665），输入功率为水力功率除以效率，
  耗能（kWh）= 输入功率(kW) × 小时。
- 成功方案按输入功率、再按名称升序排列；失败方案保留输入顺序排在末尾，
  数值字段为空。非法输入不会产生任何输出文件。

## 测试与示例

```
python -m unittest discover -s tests
python -m pumpcalc examples/pump_curve.csv examples/schemes.json out.csv out.json
```
