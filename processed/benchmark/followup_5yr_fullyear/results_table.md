| Model | Params | Mean RMSE (degC) | Mean MAE (degC) | Mean ACC | Train time (s) | Epochs |
|---|---|---|---|---|---|---|
| CNN-only | 127,913 | 0.2869 +- 0.0095 | 0.2175 +- 0.0088 | 0.8743 +- 0.0100 | 57 +- 14 | 11.4 |
| LSTM-only | 125,895 | 0.3138 +- 0.0162 | 0.2361 +- 0.0119 | 0.8600 +- 0.0132 | 39 +- 5 | 11.0 |
| Hybrid ConvLSTM | 127,239 | 0.2928 +- 0.0106 | 0.2213 +- 0.0086 | 0.8682 +- 0.0108 | 157 +- 23 | 11.2 |
| Persistence | 0 | 0.3305 | 0.2423 | 0.8597 | - | - |
| Climatology | 0 | 0.6277 | 0.5047 | n/a | - | - |

**RMSE by horizon** (test; mean +- sd over seeds)

| Horizon (d) | CNN-only | LSTM-only | Hybrid ConvLSTM | Persistence | Climatology |
|---|---|---|---|---|---|
| 1 | 0.121 +- 0.001 | 0.127 +- 0.002 | 0.120 +- 0.004 | 0.129 | 0.628 |
| 2 | 0.199 +- 0.004 | 0.211 +- 0.006 | 0.199 +- 0.006 | 0.217 | 0.627 |
| 3 | 0.255 +- 0.005 | 0.276 +- 0.010 | 0.265 +- 0.011 | 0.286 | 0.627 |
| 4 | 0.303 +- 0.008 | 0.331 +- 0.015 | 0.309 +- 0.014 | 0.346 | 0.627 |
| 5 | 0.344 +- 0.013 | 0.378 +- 0.021 | 0.352 +- 0.014 | 0.399 | 0.628 |
| 6 | 0.378 +- 0.017 | 0.418 +- 0.027 | 0.386 +- 0.015 | 0.447 | 0.628 |
| 7 | 0.409 +- 0.021 | 0.455 +- 0.033 | 0.420 +- 0.022 | 0.491 | 0.628 |

**MAE by horizon** (test; mean +- sd over seeds)

| Horizon (d) | CNN-only | LSTM-only | Hybrid ConvLSTM | Persistence | Climatology |
|---|---|---|---|---|---|
| 1 | 0.087 +- 0.001 | 0.091 +- 0.002 | 0.086 +- 0.004 | 0.091 | 0.505 |
| 2 | 0.147 +- 0.004 | 0.156 +- 0.005 | 0.147 +- 0.006 | 0.157 | 0.505 |
| 3 | 0.191 +- 0.006 | 0.206 +- 0.008 | 0.199 +- 0.010 | 0.208 | 0.504 |
| 4 | 0.229 +- 0.008 | 0.248 +- 0.012 | 0.233 +- 0.011 | 0.253 | 0.504 |
| 5 | 0.262 +- 0.011 | 0.285 +- 0.015 | 0.268 +- 0.011 | 0.293 | 0.505 |
| 6 | 0.290 +- 0.015 | 0.318 +- 0.019 | 0.295 +- 0.012 | 0.330 | 0.505 |
| 7 | 0.316 +- 0.018 | 0.348 +- 0.023 | 0.322 +- 0.016 | 0.364 | 0.505 |

**ACC by horizon** (test; mean +- sd over seeds)

| Horizon (d) | CNN-only | LSTM-only | Hybrid ConvLSTM | Persistence | Climatology |
|---|---|---|---|---|---|
| 1 | 0.981 +- 0.000 | 0.979 +- 0.001 | 0.982 +- 0.001 | 0.979 | n/a |
| 2 | 0.948 +- 0.002 | 0.943 +- 0.003 | 0.949 +- 0.003 | 0.942 | n/a |
| 3 | 0.914 +- 0.004 | 0.902 +- 0.006 | 0.907 +- 0.008 | 0.901 | n/a |
| 4 | 0.876 +- 0.007 | 0.860 +- 0.012 | 0.871 +- 0.013 | 0.858 | n/a |
| 5 | 0.837 +- 0.013 | 0.818 +- 0.018 | 0.829 +- 0.014 | 0.817 | n/a |
| 6 | 0.800 +- 0.019 | 0.778 +- 0.024 | 0.791 +- 0.017 | 0.778 | n/a |
| 7 | 0.763 +- 0.026 | 0.740 +- 0.030 | 0.749 +- 0.027 | 0.742 | n/a |

**Mean RMSE (degC) by season of the test year** (mean +- sd over seeds; n = test windows)

| Season (n) | CNN-only | LSTM-only | Hybrid ConvLSTM | Persistence |
|---|---|---|---|---|
| DJF (90) | 0.192 +- 0.002 | 0.216 +- 0.020 | 0.190 +- 0.003 | 0.243 |
| MAM (92) | 0.275 +- 0.003 | 0.299 +- 0.010 | 0.274 +- 0.002 | 0.313 |
| JJA (92) | 0.392 +- 0.020 | 0.402 +- 0.024 | 0.407 +- 0.021 | 0.426 |
| SON (78) | 0.240 +- 0.018 | 0.306 +- 0.024 | 0.246 +- 0.018 | 0.308 |

**Paired comparison, seed by seed** (difference = other model - hybrid, in degC; POSITIVE = hybrid better)

| Hybrid vs | Metric | Mean diff | sd of diff | Hybrid better in |
|---|---|---|---|---|
| CNN-only | RMSE | -0.0059 | 0.0087 | 1 of 5 seeds |
| CNN-only | MAE | -0.0038 | 0.0079 | 1 of 5 seeds |
| CNN-only | RMSE, DJF only | +0.0018 | - | 3 of 5 seeds |
| CNN-only | RMSE, MAM only | +0.0006 | - | 3 of 5 seeds |
| CNN-only | RMSE, JJA only | -0.0144 | - | 1 of 5 seeds |
| CNN-only | RMSE, SON only | -0.0062 | - | 2 of 5 seeds |
| LSTM-only | RMSE | +0.0210 | 0.0065 | 5 of 5 seeds |
| LSTM-only | MAE | +0.0148 | 0.0056 | 5 of 5 seeds |
| LSTM-only | RMSE, DJF only | +0.0256 | - | 5 of 5 seeds |
| LSTM-only | RMSE, MAM only | +0.0249 | - | 5 of 5 seeds |
| LSTM-only | RMSE, JJA only | -0.0051 | - | 1 of 5 seeds |
| LSTM-only | RMSE, SON only | +0.0602 | - | 5 of 5 seeds |
