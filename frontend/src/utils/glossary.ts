/** Plain-language definitions shown as tooltips next to technical terms. */
export const GLOSSARY = {
  sst: "Sea surface temperature: the temperature of the top layer of the ocean.",
  anomaly:
    "SST anomaly: the difference between the observed sea surface temperature and the historical average (2012-2023) for the same day of the year.",
  percentile:
    "Historical percentile: the share of baseline-year temperatures for this time of year that are lower than today's value. 95 means warmer than 95% of them.",
  mae: "Mean Absolute Error (MAE): the average difference between the predicted and the observed temperature, in degC. Lower is better.",
  rmse: "Root Mean Square Error (RMSE): like MAE but it penalises large misses more. In degC; lower is better.",
  r2: "R-squared: how much of the variation in observed temperature the forecast explains (1.0 = perfect). It is high for every method here because temperature is mostly seasonal, so compare the error columns instead.",
  persistence: "Persistence baseline: a simple prediction that assumes the current condition stays unchanged.",
  climatology: "Climatology baseline: a prediction that uses the long-term average for that day of the year.",
  heatwave:
    "Marine heatwave (project definition): SST above the seasonal 90th percentile for at least 5 days, using a simplified version of Hobday et al. (2016) with a 2012-2023 baseline. Not an official classification.",
  risk: "Project environmental risk indicator: a transparent weighted score of SST anomaly, heatwave persistence, forecast anomaly and species overlap. It shows monitoring priority, not proven harm.",
  hindcast: "Hindcast: a forecast issued in the past for days whose real observations are now known, so it can be checked.",
  forecast: "Model output: the ConvLSTM neural network's prediction. It is not an observation.",
  coverage: "The area where this project actually holds data. Outside it, the map shows nothing rather than guessing.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
