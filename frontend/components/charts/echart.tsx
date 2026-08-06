"use client";

import type { EChartsOption } from "echarts";
import { BarChart, type BarSeriesOption } from "echarts/charts";
import { LineChart, type LineSeriesOption } from "echarts/charts";
import { PieChart, type PieSeriesOption } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";

import { cn } from "@/lib/utils";

echarts.use([
  LineChart,
  BarChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,

  DataZoomComponent,
  CanvasRenderer,
]);

export type ChartOption = echarts.ComposeOption<
  LineSeriesOption | BarSeriesOption | PieSeriesOption
> &
  EChartsOption;

export function EChart({
  option,
  className,
  ariaLabel,

  fill = false,
}: {
  option: ChartOption;
  className?: string;
  ariaLabel: string;
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

        notMerge
        lazyUpdate
      />
    </div>
  );
}
