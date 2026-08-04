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

export function EChart({
  option,
  height,
  className,
  ariaLabel,
}: {
  option: ChartOption;
  height: number;
  className?: string;
  ariaLabel: string;
}) {
  return (
    <div className={className} role="img" aria-label={ariaLabel}>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height, width: "100%" }}
        opts={{ renderer: "canvas" }}
        
        
        notMerge
        lazyUpdate
      />
    </div>
  );
}
