import { LoopEvent } from './LoopEvent.js';
import { MachineSnapshot } from './MachineSnapshot.js';
import { Recommendation } from './Recommendation.js';
import { SetpointCommand } from './SetpointCommand.js';
import { TrendPoint } from './TrendPoint.js';

export type ClosedLoopSchema = {
  MachineSnapshot: MachineSnapshot;
  Recommendation: Recommendation;
  TrendPoint: TrendPoint;
  SetpointCommand: SetpointCommand;
  LoopEvent: LoopEvent;
};

export const schema = [
  MachineSnapshot,
  Recommendation,
  TrendPoint,
  SetpointCommand,
  LoopEvent,
];
