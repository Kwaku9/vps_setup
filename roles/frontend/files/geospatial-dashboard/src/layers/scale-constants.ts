import { NearFarScalar, DistanceDisplayCondition } from "cesium";

// Shared NearFarScalar values for icon scaling across layers
export const SCALE = {
  satellites: {
    point: new NearFarScalar(1e5, 2.0, 5e7, 0.15),
    label: new NearFarScalar(1e6, 1, 5e7, 0.3),
    pointDisplay: new DistanceDisplayCondition(0, 5e7),
    labelDisplay: new DistanceDisplayCondition(0, 1e7),
  },
  flights: {
    point: new NearFarScalar(1e5, 2.0, 3e7, 0.2),
    label: new NearFarScalar(1e5, 1, 5e6, 0.3),
    pointDisplay: new DistanceDisplayCondition(0, 3e7),
    labelDisplay: new DistanceDisplayCondition(0, 5e6),
  },
  military: {
    point: new NearFarScalar(1e5, 2.5, 3e7, 0.3),
    label: new NearFarScalar(1e5, 1, 5e6, 0.3),
    pointDisplay: new DistanceDisplayCondition(0, 3e7),
    labelDisplay: new DistanceDisplayCondition(0, 5e6),
  },
  earthquakes: {
    point: new NearFarScalar(1e5, 2.0, 5e7, 0.3),
    label: new NearFarScalar(1e5, 1, 5e6, 0.3),
    pointDisplay: new DistanceDisplayCondition(0, 5e7),
    labelDisplay: new DistanceDisplayCondition(0, 5e6),
  },
  cctv: {
    point: new NearFarScalar(1e3, 2.0, 1e5, 0.3),
    label: new NearFarScalar(1e3, 1, 5e4, 0.3),
    pointDisplay: new DistanceDisplayCondition(0, 1e5),
    labelDisplay: new DistanceDisplayCondition(0, 5e4),
  },
  firms: {
    point: new NearFarScalar(1e5, 2.0, 5e7, 0.3),
    label: new NearFarScalar(1e5, 1, 5e6, 0.2),
    pointDisplay: new DistanceDisplayCondition(0, 5e7),
    labelDisplay: new DistanceDisplayCondition(0, 5e6),
  },
  acled: {
    point: new NearFarScalar(1e5, 1.5, 5e7, 0.3),
    label: new NearFarScalar(1e5, 1, 5e6, 0.2),
    pointDisplay: new DistanceDisplayCondition(0, 5e7),
    labelDisplay: new DistanceDisplayCondition(0, 5e6),
  },
  maritime: {
    point: new NearFarScalar(1e5, 2.0, 5e7, 0.3),
    label: new NearFarScalar(1e5, 1, 5e6, 0.2),
    pointDisplay: new DistanceDisplayCondition(0, 5e7),
    labelDisplay: new DistanceDisplayCondition(0, 5e6),
  },
  wigle: {
    point: new NearFarScalar(100, 2.0, 1e5, 0.5),
    label: new NearFarScalar(100, 1, 2e4, 0.2),
    pointDisplay: new DistanceDisplayCondition(0, 1e5),
    labelDisplay: new DistanceDisplayCondition(0, 2e4),
  },
};
