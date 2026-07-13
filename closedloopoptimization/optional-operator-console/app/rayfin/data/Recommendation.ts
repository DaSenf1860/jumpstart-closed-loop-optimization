import { entity, role, text, uuid, set, decimal, date } from '@microsoft/rayfin-core';

// Latest pending optimizer recommendation per machine (from fn_PendingRecommendations()).
// The operator approves it to close the loop on a supervised machine.
@entity()
@role('authenticated', '*')
export class Recommendation {
  @uuid() id!: string;
  @text({ min: 1, max: 50 }) machineId!: string;
  @decimal({ precision: 7, scale: 4 }) observedDefectRate!: number;
  @decimal({ precision: 8, scale: 2 }) recommendedTemp!: number;
  @decimal({ precision: 9, scale: 2 }) recommendedPressure!: number;
  @decimal({ precision: 7, scale: 4 }) expectedDefectRate!: number;
  @text({ max: 500 }) rationale!: string;
  @set('pending', 'applied', 'dismissed') status!: 'pending' | 'applied' | 'dismissed';
  @date() createdAt!: Date;
}
