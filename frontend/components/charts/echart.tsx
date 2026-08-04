"use client";


import type { EChartsOption } from "echarts";
import { BarChart, type BarSeriesOption } from "echarts/charts";
import { LineChart, type LineSeriesOption } from "echarts/charts";
import { PieChart, type PieSeriesOption } from "echarts/charts";
import {
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
  CanvasRenderer,
]);

export type ChartOption = echarts.ComposeOption<
  LineSeriesOption | BarSeriesOption | PieSeriesOption
> &
  EChartsOption;

/**
 * The wrapper owns the height (`.chart-box` scales it with the workspace) and
 * echarts-for-react re-measures on container resize, so charts follow the
 * layout instead of being pinned to one pixel size.
 */
export function EChart({
  option,
  className,
  ariaLabel,
}: {
  option: ChartOption;
  className?: string;
  ariaLabel: string;
}) {
  return (
    <div className={cn("chart-box w-full", className)} role="img" aria-label={ariaLabel}>
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
