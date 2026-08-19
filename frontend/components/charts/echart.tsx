"use client";

import type { EChartsOption } from "echarts";
import { BarChart, type BarSeriesOption } from "echarts/charts";
import { LineChart, type LineSeriesOption } from "echarts/charts";
import { PieChart, type PieSeriesOption } from "echarts/charts";
import { HeatmapChart, type HeatmapSeriesOption } from "echarts/charts";
import { ScatterChart, type ScatterSeriesOption } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";

import { cn } from "@/lib/utils";

echarts.use([
  LineChart,
  BarChart,
  PieChart,
  HeatmapChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  MarkPointComponent,
  VisualMapComponent,

  DataZoomComponent,
  CanvasRenderer,
]);

export type ChartOption = echarts.ComposeOption<
  | LineSeriesOption
  | BarSeriesOption
  | PieSeriesOption
  | HeatmapSeriesOption
  | ScatterSeriesOption
> &
  EChartsOption;

export function EChart({
  option,
  className,
  ariaLabel,
  onEvents,
  fill = false,
}: {
  option: ChartOption;
  className?: string;
  ariaLabel: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onEvents?: Record<string, (params: any) => void>;
  fill?: boolean;
}) {
  return (
    <div
      className={cn(fill ? "h-full w-full" : "chart-box w-full", className)}
      role="img"
      aria-label={ariaLabel}
    >
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: "100%", width: "100%" }}
        opts={{ renderer: "canvas" }}
        onEvents={onEvents}
        notMerge
        lazyUpdate
      />
    </div>
  );
}
