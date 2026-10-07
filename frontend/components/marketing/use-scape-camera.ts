"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DEFAULT_CAMERA, type Camera } from "@/lib/demand-scape";

export const CAMERA_SWING = { yaw: 0.18, pitch: 0.09 };

function bounded(camera: Camera): Camera {
  return {
    yaw: Math.max(DEFAULT_CAMERA.yaw - CAMERA_SWING.yaw, Math.min(DEFAULT_CAMERA.yaw + CAMERA_SWING.yaw, camera.yaw)),
    pitch: Math.max(DEFAULT_CAMERA.pitch - CAMERA_SWING.pitch, Math.min(DEFAULT_CAMERA.pitch + CAMERA_SWING.pitch, camera.pitch)),
  };
}

export function useScapeCamera(motion: boolean) {
  const [camera, setCamera] = useState(DEFAULT_CAMERA);
  const current = useRef(DEFAULT_CAMERA);
  const anchor = useRef(DEFAULT_CAMERA);
  const target = useRef(DEFAULT_CAMERA);
  const frame = useRef(0);

  const move = useCallback((next: Camera, animate: boolean) => {
    target.current = bounded(next);
    if (!animate) {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
      current.current = target.current;
      setCamera(current.current);
      return;
    }
    if (frame.current) return;
    let previous = performance.now();
    const advance = (now: number) => {
      const weight = 1 - Math.exp(-Math.min(now - previous, 64) / 105);
      previous = now;
      const yaw = target.current.yaw - current.current.yaw;
      const pitch = target.current.pitch - current.current.pitch;
      const settled = Math.abs(yaw) + Math.abs(pitch) < 0.00008;
      current.current = settled ? target.current : {
        yaw: current.current.yaw + yaw * weight,
        pitch: current.current.pitch + pitch * weight,
      };
      setCamera(current.current);
      frame.current = settled ? 0 : requestAnimationFrame(advance);
    };
    frame.current = requestAnimationFrame(advance);
  }, []);

  const rotate = useCallback((next: Camera) => {
    anchor.current = bounded(next);
    move(anchor.current, false);
  }, [move]);

  const grab = useCallback(() => {
    move(current.current, false);
    return current.current;
  }, [move]);

  const orbit = useCallback((x: number, y: number) => {
    if (!motion) return;
    move({ yaw: anchor.current.yaw + x * 0.09, pitch: anchor.current.pitch - y * 0.045 }, true);
  }, [motion, move]);

  const rest = useCallback((animate = motion) => move(anchor.current, animate), [motion, move]);

  useEffect(() => {
    if (!motion) move(anchor.current, false);
    return () => {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
    };
  }, [motion, move]);

  return { camera, orbit, rotate, grab, rest };
}
