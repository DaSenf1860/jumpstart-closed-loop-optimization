import { entity, role, text, uuid, date } from '@microsoft/rayfin-core';

// A human-readable audit-feed entry for the closed loop (optimizer applies,
// operator approvals, mode changes, recommendations). Appended by the bridge
// and by the console when the operator acts.
@entity()
@role('authenticated', '*')
export class LoopEvent {
  @uuid() id!: string;
  @text({ min: 1, max: 50 }) machineId!: string;
  @date() ts!: Date;
  @text({ min: 1, max: 50 }) kind!: string;
  @text({ min: 1, max: 500 }) message!: string;
}
