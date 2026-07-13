import { entity, role, text, uuid, set, decimal, int, date } from '@microsoft/rayfin-core';

// Latest KPI snapshot per machine. Upserted by the KQL<->SQL bridge job from
// fn_LiveKpis(). The operator console reads and polls this.
@entity()
@role('authenticated', '*')
export class MachineSnapshot {
  @uuid() id!: string;
  @text({ min: 1, max: 50 }) machineId!: string;
  @text({ min: 1, max: 50 }) lineId!: string;
  @text({ min: 1, max: 100 }) product!: string;
  @set('auto', 'supervised') mode!: 'auto' | 'supervised';
  @set('healthy', 'warning', 'critical') status!: 'healthy' | 'warning' | 'critical';
  @decimal({ precision: 7, scale: 4 }) currentDefectRate!: number;
  @decimal({ precision: 8, scale: 2 }) tempC!: number;
  @decimal({ precision: 9, scale: 2 }) pressureBar!: number;
  @decimal({ precision: 8, scale: 2 }) tempSetpoint!: number;
  @decimal({ precision: 9, scale: 2 }) pressureSetpoint!: number;
  @decimal({ precision: 6, scale: 2 }) coolingTimeS!: number;
  @int() parts!: number;
  @int() defects!: number;
  @decimal({ precision: 7, scale: 3 }) vibration!: number;
  @date() updatedAt!: Date;
}
