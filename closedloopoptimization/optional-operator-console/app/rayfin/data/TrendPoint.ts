import { entity, role, text, uuid, decimal, date } from '@microsoft/rayfin-core';

// Downsampled defect-rate trend per machine for the console sparklines/charts.
// The bridge appends new points and prunes to a rolling window.
@entity()
@role('authenticated', '*')
export class TrendPoint {
  @uuid() id!: string;
  @text({ min: 1, max: 50 }) machineId!: string;
  @date() ts!: Date;
  @decimal({ precision: 7, scale: 4 }) defectRate!: number;
  @decimal({ precision: 8, scale: 2 }) tempSetpoint!: number;
}
