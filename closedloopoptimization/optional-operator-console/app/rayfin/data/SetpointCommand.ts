import { entity, role, text, uuid, set, decimal, email, date } from '@microsoft/rayfin-core';

// An operator-initiated command. The console writes rows with status='requested';
// the KQL<->SQL bridge job applies them to the MfgRTI Setpoints table (closing
// the loop) and marks them 'applied' (or 'error'). `kind` distinguishes a
// setpoint change from a mode (auto/supervised) change; all fields carry the
// intended post-command state so the bridge can write a single Setpoints row.
@entity()
@role('authenticated', '*')
export class SetpointCommand {
  @uuid() id!: string;
  @text({ min: 1, max: 50 }) machineId!: string;
  @set('setpoint', 'mode') kind!: 'setpoint' | 'mode';
  @decimal({ precision: 8, scale: 2 }) tempSetpoint!: number;
  @decimal({ precision: 9, scale: 2 }) pressureSetpoint!: number;
  @decimal({ precision: 6, scale: 2 }) coolingTimeS!: number;
  @set('auto', 'supervised') mode!: 'auto' | 'supervised';
  @email() requestedBy!: string;
  @set('requested', 'applied', 'error') status!: 'requested' | 'applied' | 'error';
  @text({ optional: true, max: 300 }) note?: string;
  @date() createdAt!: Date;
  @date({ optional: true }) appliedAt?: Date;
}
