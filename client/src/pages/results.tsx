import { useMemo, useState, useCallback } from "react";
import { useParams, useLocation } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { PageSkeleton } from "@/components/page-skeleton";
import { filterByDateRange, takeLastN, exportForecastCsv } from "@/utils/forecastUtils";
import type { ResultsResponse, ResultRow } from "@shared/schema";
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ScatterChart, Scatter, ReferenceLine,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ComposedChart, ReferenceArea,
} from "recharts";

import {
  TrendingUp, Trophy, Download, Home, BarChart3, Activity,
  GitCompare, Target, Clock, CheckCircle2, Layers, Sliders, FileText, Lightbulb, Filter
} from "lucide-react";

const HORIZON_OPTIONS = [60, 120, 240, 500, 1000, 0] as const; // 0 = all
const COMPARISON_METRICS = ["rmse", "mae", "mape", "r2"] as const;
type ComparisonMetric = typeof COMPARISON_METRICS[number];

const COLORS = [
  "hsl(217, 91%, 60%)", "hsl(262, 83%, 58%)", "hsl(160, 60%, 45%)",
  "hsl(43, 96%, 56%)", "hsl(27, 87%, 55%)", "hsl(350, 60%, 52%)", "hsl(190, 70%, 50%)",
];

export default function ResultsPage() {
  const params = useParams<{ jobId: string }>();
  const [, navigate] = useLocation();
  const jobId = params.jobId || "";

  const { data, isLoading } = useQuery<ResultsResponse>({
    queryKey: ["/api/results", jobId],
    enabled: !!jobId,
    refetchInterval: (query) => query.state.data?.status === "completed" ? false : 3000,
  });

  const [selectedModel, setSelectedModel] = useState<string>("all");
  const [scenarioMultiplier, setScenarioMultiplier] = useState<number>(0);
  const [dateRange, setDateRange] = useState<{ start: string; end: string } | null>(null);
  const [horizon, setHorizon] = useState<number>(60);
  const [selectedModelIds, setSelectedModelIds] = useState<Set<string>>(new Set());
  const [comparisonMetric, setComparisonMetric] = useState<ComparisonMetric>("rmse");
  const [filtersOpen, setFiltersOpen] = useState(true);
  const results: ResultRow[] = data?.results ?? [];
  const bestModel = results.find((r) => r.is_best);

  const allDates = useMemo(() => {
    if (!results.length) return [];
    const set = new Set<string>();
    const r = results[0]; // Optimization: assumed all have same dates
    (r.predictions || []).forEach((p) => p.date && set.add(p.date.slice(0, 10)));
    (r.forecast || []).forEach((f) => f.date && set.add(f.date?.slice(0, 10)));
    return Array.from(set).sort();
  }, [results]);
  const defaultStart = allDates[0] ?? "";
  const defaultEnd = allDates[allDates.length - 1] ?? "";
  const filterStart = dateRange?.start ?? defaultStart;
  const filterEnd = dateRange?.end ?? defaultEnd;

  const filterByDate = useCallback(
    (dateStr: string) => filterByDateRange(dateStr, filterStart, filterEnd),
    [filterStart, filterEnd]
  );

  const takeHorizon = useCallback(
    <T,>(arr: T[]) => takeLastN(arr, horizon),
    [horizon]
  );

  const visibleResults = useMemo(() => {
    if (!selectedModelIds.size) return results;
    return results.filter((r) => selectedModelIds.has(r.model_name));
  }, [results, selectedModelIds]);

  const radarData = useMemo(() => {
    if (!visibleResults.length) return [];
    const keys = ["mae", "rmse", "mape"] as const;
    const mx: Record<string, number> = {};
    keys.forEach((k) => { mx[k] = Math.max(...visibleResults.map((r) => Number(r.metrics?.[k]) || 0), 0.001); });
    return keys.map((k) => {
      const e: Record<string, unknown> = { metric: k.toUpperCase() };
      visibleResults.forEach((r) => { e[r.model_name] = Math.max(0, 1 - (Number(r.metrics?.[k]) || 0) / mx[k]); });
      return e;
    }).concat([{
      metric: "R\u00B2",
      ...Object.fromEntries(visibleResults.map((r) => [r.model_name, Math.max(0, r.metrics?.r2 || 0)])),
    }]);
  }, [visibleResults]);

  const forecastChartData = useMemo(() => {
    if (!visibleResults.length) return [];
    const base = visibleResults[0];
    const actual = (base.predictions || []).filter((p) => filterByDate(p.date ?? "")).map((p) => ({
      date: p.date?.slice(0, 10), Actual: p.actual,
    }));

    // FIX Bug 28: Build a date-keyed map per model instead of aligning by index
    const modelFcMaps: Record<string, Record<string, number>> = {};
    visibleResults.forEach((r) => {
      modelFcMaps[r.model_name] = {};
      (r.forecast || []).forEach((f) => {
        if (f.date) modelFcMaps[r.model_name][f.date.slice(0, 10)] = Math.round((f.predicted ?? 0) * 100) / 100;
      });
    });

    // Optimization: avoid mapping all models
    const fcDates = (base.forecast || [])
      .map((f) => f.date?.slice(0, 10) ?? "")
      .filter((d) => d && filterByDate(d))
      .sort();

    const fc = fcDates.map((date) => {
      const e: Record<string, unknown> = { date };
      visibleResults.forEach((r) => {
        if (modelFcMaps[r.model_name][date] !== undefined)
          e[r.model_name] = modelFcMaps[r.model_name][date];
      });
      return e;
    });

    let combined: Record<string, unknown>[] = [];
    if (actual.length && fc.length) {
      const last = actual[actual.length - 1];
      const bridge: Record<string, unknown> = { date: last.date, Actual: last.Actual };
      visibleResults.forEach((r) => { bridge[r.model_name] = last.Actual; });
      combined = [...actual, bridge, ...fc];
    } else {
      combined = [...actual, ...fc];
    }
    return takeHorizon(combined);
  }, [visibleResults, filterByDate, takeHorizon]);

  const selectedData = useMemo(() => {
    if (selectedModel === "all") return null;
    return results.find((r) => r.model_name === selectedModel) ?? null;
  }, [results, selectedModel]);

  const scenarioData = useMemo(() => {
    if (!bestModel) return [];
    const actual = (bestModel.predictions || []).filter((p) => filterByDate(p.date ?? "")).map((p) => ({
      date: p.date?.slice(0, 10), Actual: p.actual,
    }));
    const fc = (bestModel.forecast || []).filter((f) => filterByDate(f.date ?? "")).map((f) => {
      const mult = 1 + (scenarioMultiplier / 100);
      return {
        date: f.date?.slice(0, 10),
        Base: Math.round((f.predicted ?? 0) * 100) / 100,
        Simulated: Math.round((f.predicted ?? 0) * mult * 100) / 100,
      };
    });
    let combined: Record<string, unknown>[] = [];
    if (actual.length && fc.length) {
      const last = actual[actual.length - 1];
      const bridge = { date: last.date, Actual: last.Actual, Base: last.Actual, Simulated: last.Actual };
      combined = [...actual, bridge, ...fc];
    } else {
      combined = [...actual, ...fc];
    }
    return takeHorizon(combined);
  }, [bestModel, scenarioMultiplier, filterByDate, takeHorizon]);

  const residualData = useMemo(() => {
    if (!selectedData) return [];
    return (selectedData.residuals || []).map((r, i) => ({ index: i, residual: r }));
  }, [selectedData]);

  const actualVsPred = useMemo(() => {
    if (!selectedData) return [];
    return (selectedData.predictions || [])
      .filter((p) => p.actual != null && p.predicted != null)
      .map((p) => ({ date: p.date?.slice(0, 10), Actual: p.actual, Predicted: p.predicted }));
  }, [selectedData]);

  const downloadCSV = useCallback(() => {
    if (!bestModel) return;
    exportForecastCsv(bestModel, jobId);
  }, [bestModel, jobId]);

  if (isLoading) {
    return <PageSkeleton />;
  }

  const IN_PROGRESS_STATUSES = ["queued", "processing", "preprocessing", "training"];
  if (data && IN_PROGRESS_STATUSES.includes(data.status)) {
    return (
      <div className="flex items-center justify-center h-full">
        <Card className="max-w-md">
          <CardContent className="py-8 flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-muted-foreground">Training still in progress...</p>
            <Button variant="outline" onClick={() => navigate(`/training/${jobId}`)}>View Progress</Button>
          </CardContent>
        </Card>
      </div>
    );
  }


  const tooltipStyle = { backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: "8px", fontSize: 12 };

  const containerVariants = {
    hidden: { opacity: 0 },
    show: { opacity: 1, transition: { staggerChildren: 0.1 } }
  };
  const itemVariants = {
    hidden: { opacity: 0, y: 10 },
    show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } }
  };

  return (
    <motion.div initial="hidden" animate="show" variants={containerVariants} className="p-6 max-w-7xl mx-auto space-y-6">
      <Breadcrumbs items={[{ label: "Home", href: "/" }, { label: "Results" }, { label: jobId }]} className="print:hidden" />
      {/* Header */}
      <motion.div variants={itemVariants} className="flex items-center justify-between print:hidden">
        <div>
          <h1 className="text-lg font-semibold">Forecast Results</h1>
          <p className="text-xs text-muted-foreground font-mono mt-0.5">{jobId}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => window.print()} className="gap-1.5" data-testid="btn-pdf">
            <FileText className="w-3.5 h-3.5" /> Save PDF
          </Button>
          <Button variant="outline" size="sm" onClick={downloadCSV} className="gap-1.5" data-testid="btn-export">
            <Download className="w-3.5 h-3.5" /> Export CSV
          </Button>
          <Button variant="outline" size="sm" onClick={() => navigate("/")} className="gap-1.5" data-testid="btn-new">
            <Home className="w-3.5 h-3.5" /> New
          </Button>
        </div>
      </motion.div>

      {/* Print-only header */}
      <div className="hidden print:block mb-8">
        <h1 className="text-2xl font-bold mb-1">Executive Forecast Report</h1>
        <p className="text-sm text-muted-foreground">Generated by ForecastHub AI — Job ID: {jobId}</p>
      </div>

      {/* Best Model Banner with Aurora effect */}
      {bestModel && (
        <motion.div variants={itemVariants}>
          <Card className="border-0 shadow-lg relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-r from-primary/20 via-chart-2/20 to-primary/20 animate-gradient-x opacity-80 mix-blend-overlay"></div>
            <div className="absolute -inset-1 bg-gradient-to-r from-primary to-chart-2 blur-md opacity-20 group-hover:opacity-40 transition-opacity duration-500"></div>
            <CardContent className="py-4 relative z-10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 backdrop-blur-sm bg-card/80">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 shadow-[0_0_15px_rgba(var(--primary),0.3)]">
                  <Trophy className="w-6 h-6 text-primary" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-muted-foreground uppercase tracking-widest mb-0.5">Best Model</p>
                  <div className="flex items-end gap-3">
                    <span className="text-2xl font-bold gradient-text">{bestModel.model_name}</span>
                    <p className="text-sm text-muted-foreground mb-1 font-medium">
                      RMSE: {bestModel.metrics?.rmse?.toFixed(2)} <span className="mx-1 opacity-50">•</span> MAE: {bestModel.metrics?.mae?.toFixed(2)} <span className="mx-1 opacity-50">•</span> R²: <span className="text-foreground">{bestModel.metrics?.r2?.toFixed(4)}</span>
                    </p>
                  </div>
                </div>
              </div>
              <Badge className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/30 px-3 py-1 text-sm font-semibold">Recommended Endpoint</Badge>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* KPIs */}
      <motion.div variants={itemVariants} className="grid grid-cols-2 md:grid-cols-4 gap-4" role="region" aria-label="Summary metrics">
        {[
          { icon: Layers, label: "Models", value: String(results.length) },
          { icon: Target, label: "Best RMSE", value: bestModel?.metrics?.rmse?.toFixed(2) ?? "—" },
          { icon: BarChart3, label: "Best R²", value: bestModel?.metrics?.r2?.toFixed(4) ?? "—" },
          { icon: Clock, label: "Total Time", value: `${results.reduce((s, r) => s + (r.training_time ?? 0), 0).toFixed(1)}s` },
        ].map((kpi) => {
          const Icon = kpi.icon;
          return (
            <Card key={kpi.label} className="glass-card hover:-translate-y-1 transition-transform duration-300" aria-label={`${kpi.label}: ${kpi.value}`}>
              <CardContent className="py-4 relative overflow-hidden">
                <div className="absolute -right-4 -top-4 w-16 h-16 bg-primary/5 rounded-full pointer-events-none blur-xl"></div>
                <p className="text-[11px] font-semibold tracking-wider uppercase text-muted-foreground flex items-center gap-1.5 mb-1.5"><Icon className="w-3.5 h-3.5 text-primary/70" aria-hidden /> {kpi.label}</p>
                <p className="text-2xl font-bold tabular-nums text-foreground tracking-tight">{kpi.value}</p>
              </CardContent>
            </Card>
          );
        })}
      </motion.div>

      {/* Chart filters */}
      <motion.div variants={itemVariants}>
        <Card className="glass-card">
          <CardHeader className="py-3 print:hidden border-b border-border/40">
            <Button variant="ghost" size="sm" className="gap-2 -ml-2 hover:bg-primary/5 hover:text-primary transition-colors" onClick={() => setFiltersOpen((o) => !o)}>
              <Filter className="w-4 h-4" />
              <CardTitle className="text-sm font-semibold">Chart filters</CardTitle>
            </Button>
          </CardHeader>
          {filtersOpen && (
            <CardContent className="pt-4 pb-5 print:hidden space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-1.5">
                  <Label className="text-xs">Date range (start)</Label>
                  <input
                    type="date"
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                    value={filterStart}
                    onChange={(e) => setDateRange((prev) => ({ ...prev ?? { start: defaultStart, end: defaultEnd }, start: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Date range (end)</Label>
                  <input
                    type="date"
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                    value={filterEnd}
                    onChange={(e) => setDateRange((prev) => ({ ...prev ?? { start: defaultStart, end: defaultEnd }, end: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Horizon (points)</Label>
                  <Select value={horizon === 0 ? "all" : String(horizon)} onValueChange={(v) => setHorizon(v === "all" ? 0 : parseInt(v, 10))}>
                    <SelectTrigger className="text-xs"><SelectValue placeholder="Points to show" /></SelectTrigger>
                    <SelectContent>
                      {HORIZON_OPTIONS.filter((n) => n > 0).map((n) => (
                        <SelectItem key={n} value={String(n)}>Last {n}</SelectItem>
                      ))}
                      <SelectItem value="all">All</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Models in charts</Label>
                  <div className="flex flex-wrap gap-2">
                    {results.map((r) => {
                      const isChecked = selectedModelIds.size === 0 || selectedModelIds.has(r.model_name);
                      return (
                        <label key={r.model_name} className="flex items-center gap-1.5 text-xs cursor-pointer">
                          <Checkbox
                            checked={isChecked}
                            onCheckedChange={(checked) => {
                              setSelectedModelIds((prev): Set<string> => {
                                const allNames = new Set<string>(results.map((x) => String(x.model_name)));
                                if (prev.size === 0) {
                                  if (checked) return prev;
                                  allNames.delete(r.model_name);
                                  return allNames;
                                }
                                const next = new Set(prev);
                                if (checked) next.add(r.model_name); else next.delete(r.model_name);
                                return next.size === 0 ? new Set<string>() : next;
                              });
                            }}
                          />
                          <span>{r.model_name}{r.is_best ? " ★" : ""}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>
            </CardContent>
          )}
        </Card>
      </motion.div>

      {/* Tabs */}
      <motion.div variants={itemVariants}>
        <Tabs defaultValue="forecast" className="w-full">
          <TabsList className="w-full justify-start flex-wrap gap-1 print:hidden">
            <TabsTrigger value="forecast" className="gap-1.5 text-xs"><TrendingUp className="w-3.5 h-3.5" /> Forecast</TabsTrigger>
            <TabsTrigger value="scenario" className="gap-1.5 text-xs"><Sliders className="w-3.5 h-3.5" /> What-If</TabsTrigger>
            <TabsTrigger value="insights" className="gap-1.5 text-xs"><Lightbulb className="w-3.5 h-3.5" /> Insights & XAI</TabsTrigger>
            <TabsTrigger value="comparison" className="gap-1.5 text-xs"><GitCompare className="w-3.5 h-3.5" /> Comparison</TabsTrigger>
            <TabsTrigger value="detailed" className="gap-1.5 text-xs"><Activity className="w-3.5 h-3.5" /> Detailed</TabsTrigger>
            <TabsTrigger value="metrics" className="gap-1.5 text-xs"><BarChart3 className="w-3.5 h-3.5" /> Metrics Table</TabsTrigger>
          </TabsList>

          {/* Comparison Tab */}
          <TabsContent value="comparison" className="mt-4 space-y-5">
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div>
                    <CardTitle className="text-sm">Metric Comparison</CardTitle>
                    <CardDescription className="text-xs">{comparisonMetric === "r2" ? "Higher is better" : "Lower is better"}</CardDescription>
                  </div>
                  <Select value={comparisonMetric} onValueChange={(v) => setComparisonMetric(v as ComparisonMetric)}>
                    <SelectTrigger className="w-36 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {COMPARISON_METRICS.map((m) => (
                        <SelectItem key={m} value={m}>{m.toUpperCase()}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </CardHeader>
              <CardContent>
                <div className="h-64" role="img" aria-label={`Metric comparison: ${comparisonMetric.toUpperCase()} by model`}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={visibleResults.map((r) => ({ name: r.model_name, [comparisonMetric.toUpperCase()]: r.metrics?.[comparisonMetric] }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Bar dataKey={comparisonMetric.toUpperCase()} fill={COLORS[0]} radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Performance Radar</CardTitle>
                <CardDescription className="text-xs">Normalized scores (higher is better)</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-72" role="img" aria-label="Performance radar: normalized metrics by model">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={radarData}>
                      <PolarGrid stroke="hsl(var(--border))" />
                      <PolarAngleAxis dataKey="metric" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <PolarRadiusAxis angle={30} domain={[0, 1]} tick={{ fontSize: 9 }} stroke="hsl(var(--muted-foreground))" />
                      {/* FIX Bug 27: Use visibleResults instead of results so filter checkboxes work correctly */}
                      {visibleResults.map((r, i) => (
                        <Radar key={r.model_name} name={r.model_name} dataKey={r.model_name} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.08} strokeWidth={r.is_best ? 2.5 : 1.5} />
                      ))}
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Tooltip contentStyle={tooltipStyle} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Training Time</CardTitle></CardHeader>
              <CardContent>
                <div className="h-40" role="img" aria-label="Training time in seconds by model">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={visibleResults.map((r) => ({ name: r.model_name, time: r.training_time }))} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={100} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Bar dataKey="time" fill={COLORS[2]} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Forecast Tab */}
          <TabsContent value="forecast" className="mt-6 space-y-6">
            <Card className="glass-card">
              <CardHeader className="pb-4">
                <CardTitle className="text-base font-semibold">All Models Forecast Comparison</CardTitle>
                <CardDescription className="text-xs font-medium">Recent actuals + future predictions</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-80" role="img" aria-label="Forecast comparison: actual values and model predictions over time">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={forecastChartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" interval="preserveStartEnd" />
                      <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line dataKey="Actual" stroke="hsl(var(--foreground))" strokeWidth={2} dot={false} />
                      {visibleResults.map((r, i) => (
                        <Line key={r.model_name} dataKey={r.model_name} stroke={COLORS[i % COLORS.length]} strokeWidth={r.is_best ? 2.5 : 1.5} strokeDasharray={r.is_best ? undefined : "5 5"} dot={false} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
            {bestModel && (
              <Card className="glass-card border-primary/20 shadow-[0_4px_20px_rgba(var(--primary),0.05)]">
                <CardHeader className="pb-4 border-b border-border/30">
                  <CardTitle className="text-base font-semibold flex items-center gap-2">
                    <Trophy className="w-4 h-4 text-primary" />
                    {bestModel.model_name} — Confidence Interval
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4">
                  <div className="h-72" role="img" aria-label={`${bestModel.model_name} forecast with confidence interval bounds`}>
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={bestModel.forecast}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => v?.slice(0, 10)} interval="preserveStartEnd" />
                        <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                        <Tooltip contentStyle={tooltipStyle} />
                        {/*
                          FIX Bug 26: Correct CI band rendering.
                          Strategy: render 'upper' as a filled area from 0 to upper.
                          Then render 'lower' as a filled area from 0 to lower in card background color
                          to "erase" below lower bound. Finally overlay the predicted line.
                          This is the correct Recharts pattern for CI bands.
                        */}
                        <Area
                          dataKey="upper"
                          stroke="none"
                          fill={COLORS[0]}
                          fillOpacity={0.18}
                          name="Upper CI"
                          legendType="none"
                          isAnimationActive={false}
                        />
                        <Area
                          dataKey="lower"
                          stroke="none"
                          fill="hsl(var(--background))"
                          fillOpacity={1}
                          name="Lower CI"
                          legendType="none"
                          isAnimationActive={false}
                        />
                        <Line dataKey="predicted" stroke={COLORS[0]} strokeWidth={2} dot={false} type="monotone" name="Forecast" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Scenario Tab */}
          <TabsContent value="scenario" className="mt-4 space-y-5">
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-sm">What-If Scenario Analysis</CardTitle>
                    <CardDescription className="text-xs">Simulate future external conditions on {bestModel?.model_name}</CardDescription>
                  </div>
                  <Badge variant="outline" className={`text-xs font-mono ${scenarioMultiplier > 0 ? "text-green-500 border-green-500/50" : scenarioMultiplier < 0 ? "text-red-500 border-red-500/50" : ""}`}>
                    {scenarioMultiplier > 0 ? '+' : ''}{scenarioMultiplier}%
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="pt-2 pb-4">
                  <p className="text-xs text-muted-foreground mb-4 text-center">Adjust forecast impact multiplier (e.g. market upturn, seasonal adjustment, intervention effect):</p>

                  <Slider
                    value={[scenarioMultiplier]}
                    min={-50} max={50} step={1}
                    onValueChange={(v) => setScenarioMultiplier(v[0])}
                    className="w-full"
                  />
                  <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                    <span>-50% (significant reduction)</span>
                    <span className="font-semibold text-foreground">
                      {scenarioMultiplier > 0 ? "+" : ""}{scenarioMultiplier}%
                    </span>
                    <span>+50% (significant increase)</span>
                  </div>
                </div>

                <div className="h-80" role="img" aria-label="What-if scenario: base vs simulated forecast">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={scenarioData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" interval="preserveStartEnd" />
                      <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" domain={['auto', 'auto']} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line dataKey="Actual" stroke="hsl(var(--foreground))" strokeWidth={2} dot={false} />
                      <Line dataKey="Base" stroke={COLORS[0]} strokeWidth={1.5} strokeDasharray="5 5" dot={false} />
                      <Line dataKey="Simulated" stroke={COLORS[1]} strokeWidth={2.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Insights / XAI Tab */}
          <TabsContent value="insights" className="mt-4 space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">

              {/* Data Profile summary */}
              <Card className="glass-card flex flex-col h-full bg-gradient-to-br from-card/80 to-blue-500/5 group border-blue-500/20 hover:border-blue-500/40">
                <CardHeader className="pb-4">
                  <div className="flex items-center gap-2 mb-1">
                    <div className="p-2 rounded-md bg-blue-500/10 text-blue-500">
                      <Target className="w-4 h-4" />
                    </div>
                    <CardTitle className="text-sm">Data Profile</CardTitle>
                  </div>
                  <CardDescription className="text-xs">Summary statistics from the dataset</CardDescription>
                </CardHeader>
                <CardContent className="flex-1">
                  <div className="grid grid-cols-2 gap-x-4 gap-y-6">
                    {data?.preprocessing?.statistics && Object.entries(data.preprocessing.statistics).map(([k, v]) => (
                      <div key={k} className="space-y-1">
                        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{k}</p>
                        <p className="text-sm font-semibold tabular-nums tracking-tight">{String(v)}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* Stationarity Analysis */}
              <Card className="glass-card flex flex-col h-full bg-gradient-to-br from-card/80 to-purple-500/5 group border-purple-500/20 hover:border-purple-500/40">
                <CardHeader className="pb-4">
                  <div className="flex items-center gap-2 mb-1">
                    <div className="p-2 rounded-md bg-purple-500/10 text-purple-500">
                      <Activity className="w-4 h-4" />
                    </div>
                    <CardTitle className="text-sm">Stationarity</CardTitle>
                  </div>
                  <CardDescription className="text-xs">Dickey-Fuller test results</CardDescription>
                </CardHeader>
                <CardContent className="flex-1 flex flex-col justify-between">
                  <div>
                    <div className="flex items-center gap-3 mb-3">
                      <Badge variant={data?.preprocessing?.stationarity?.is_stationary ? "default" : "secondary"} className={data?.preprocessing?.stationarity?.is_stationary ? "bg-green-500/15 text-green-700 hover:bg-green-500/25 border-green-500/20" : ""}>
                        {data?.preprocessing?.stationarity?.is_stationary ? "Stationary Signal" : "Non-Stationary"}
                      </Badge>
                      <span className="text-xs font-mono text-muted-foreground">p-value: {data?.preprocessing?.stationarity?.p_value}</span>
                    </div>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {data?.preprocessing?.stationarity?.is_stationary
                        ? "The time series properties do not depend on the time at which the series is observed. The data lacks strong trends or growing seasonality, making it easier for statistical models to forecast reliably."
                        // FIX Bug 30: Corrected non-stationary description — differencing removes trends, doesn't 'identify signal'
                        : "The statistical properties of the series change over time (e.g., growing trend, changing variance). Models like ARIMA apply differencing to remove trends and stabilize the variance before fitting."}
                    </p>
                  </div>
                </CardContent>
              </Card>

              {/* Seasonality Detection */}
              <Card className="glass-card flex flex-col h-full bg-gradient-to-br from-card/80 to-amber-500/5 group border-amber-500/20 hover:border-amber-500/40">
                <CardHeader className="pb-4">
                  <div className="flex items-center gap-2 mb-1">
                    <div className="p-2 rounded-md bg-amber-500/10 text-amber-500">
                      <Sliders className="w-4 h-4" />
                    </div>
                    <CardTitle className="text-sm">Seasonality</CardTitle>
                  </div>
                  <CardDescription className="text-xs">Periodic pattern detection</CardDescription>
                </CardHeader>
                <CardContent className="flex-1 flex flex-col justify-between">
                  <div>
                    {data?.preprocessing?.seasonality?.detected ? (
                      <>
                        <div className="flex items-center gap-3 mb-3">
                          <Badge variant="outline" className="border-amber-500/30 text-amber-700 bg-amber-500/5">
                            Period: {data.preprocessing.seasonality.period}
                          </Badge>
                          <span className="text-xs font-medium text-muted-foreground">
                            Strength: <span className="font-semibold text-foreground">{data.preprocessing.seasonality.strength?.toFixed(2) || "Strong"}</span>
                          </span>
                        </div>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          Strong periodic seasonality was detected in the dataset. The analysis engine automatically factored this cyclic nature into the predictive models to capture recurring peaks and troughs accurately.
                        </p>
                      </>
                    ) : (
                      <>
                        <div className="flex items-center gap-3 mb-3">
                          <Badge variant="secondary">No Seasonality</Badge>
                        </div>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          No dominant repeating patterns (seasonality) were detected in the data. Predictive models therefore relied primarily on linear trends, historical lags, and exogenous factors rather than repeating cycles.
                        </p>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Data Quality Warnings */}
              {data?.preprocessing?.warnings && data.preprocessing.warnings.length > 0 && (
                <Card className="md:col-span-2 lg:col-span-3 border-amber-500/30 bg-gradient-to-r from-amber-500/10 to-transparent">
                  <CardHeader className="pb-2">
                    <div className="flex items-center gap-2 mb-1">
                      <Lightbulb className="w-4 h-4 text-amber-600" />
                      <CardTitle className="text-sm text-amber-800 dark:text-amber-500">Data Quality Notes</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <ul className="text-sm text-amber-900/80 dark:text-amber-200/80 space-y-2 list-disc pl-5">
                      {data.preprocessing.warnings.map((w: string, i: number) => (
                        <li key={i} className="pl-1">{w}</li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>

          {/* Detailed Tab */}
          <TabsContent value="detailed" className="mt-4 space-y-5">
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger className="w-56" data-testid="select-detail-model"><SelectValue placeholder="Select model" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Select a model</SelectItem>
                {results.map((r) => (
                  <SelectItem key={r.model_name} value={r.model_name}>{r.model_name} {r.is_best ? "\u2605" : ""}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedData ? (
              <>
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">{selectedData.model_name} — Actual vs Predicted</CardTitle></CardHeader>
                  <CardContent>
                    <div className="h-72" role="img" aria-label={`${selectedData.model_name} actual vs predicted values`}>
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={actualVsPred}>
                          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                          <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" interval="preserveStartEnd" />
                          <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                          <Tooltip contentStyle={tooltipStyle} />
                          <Legend wrapperStyle={{ fontSize: 11 }} />
                          <Line dataKey="Actual" stroke="hsl(var(--foreground))" strokeWidth={1.5} dot={false} />
                          <Line dataKey="Predicted" stroke={COLORS[0]} strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{selectedData.model_name} — Residuals</CardTitle>
                    <CardDescription className="text-xs">Should be randomly distributed around zero</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="h-56" role="img" aria-label={`${selectedData.model_name} residuals distribution`}>
                      <ResponsiveContainer width="100%" height="100%">
                        <ScatterChart>
                          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                          <XAxis dataKey="index" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
                          <YAxis dataKey="residual" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
                          <Tooltip contentStyle={tooltipStyle} />
                          <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
                          <Scatter data={residualData} fill={COLORS[0]} fillOpacity={0.6} r={3} />
                        </ScatterChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
                {selectedData.parameters && Object.keys(selectedData.parameters).length > 0 && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Model Parameters</CardTitle></CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                        {Object.entries(selectedData.parameters).map(([k, v]) => (
                          <div key={k} className="bg-muted/50 rounded-md p-2.5">
                            <p className="text-[10px] text-muted-foreground">{k}</p>
                            <p className="text-sm font-mono font-medium mt-0.5 break-all">{String(v)}</p>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
                {selectedData.tuning_metrics && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Hyperparameter Tuning</CardTitle></CardHeader>
                    <CardContent>
                      <div className="bg-muted/50 rounded-md p-3 space-y-3">
                        <div className="flex items-center justify-between border-b pb-2">
                          <span className="text-xs text-muted-foreground">Combinations Tested:</span>
                          <span className="text-sm font-semibold">{selectedData.tuning_metrics.combinations_tested}</span>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground mb-1">Selected Parameters:</p>
                          <div className="grid grid-cols-2 gap-2 mt-1">
                            {Object.entries(selectedData.tuning_metrics.selected_params).map(([k, v]) => (
                              <div key={`param-${k}`} className="text-xs">
                                <span className="font-semibold text-foreground/80">{k}:</span> <span className="font-mono">{String(v)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <Card>
                <CardContent className="py-12 flex flex-col items-center">
                  <Activity className="w-8 h-8 text-muted-foreground mb-2" />
                  <p className="text-sm text-muted-foreground">Select a model for detailed analysis</p>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Metrics Table */}
          <TabsContent value="metrics" className="mt-4">
            <Card>
              <CardContent className="pt-4 overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">Model</TableHead>
                      <TableHead className="text-xs text-right">MAE</TableHead>
                      <TableHead className="text-xs text-right">RMSE</TableHead>
                      <TableHead className="text-xs text-right">MAPE (%)</TableHead>
                      <TableHead className="text-xs text-right">R²</TableHead>
                      <TableHead className="text-xs text-right">AIC</TableHead>
                      <TableHead className="text-xs text-right">BIC</TableHead>
                      <TableHead className="text-xs text-right">Time (s)</TableHead>
                      <TableHead className="text-xs text-center">Best</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...results].sort((a, b) => (a.metrics?.rmse ?? Infinity) - (b.metrics?.rmse ?? Infinity)).map((r) => (
                      <TableRow key={r.model_name} className={r.is_best ? "bg-primary/5" : ""}>
                        <TableCell className="text-sm font-medium">{r.model_name}</TableCell>
                        <TableCell className="text-sm font-mono text-right tabular-nums">{r.metrics?.mae?.toFixed(4) ?? "—"}</TableCell>
                        <TableCell className="text-sm font-mono text-right tabular-nums">{r.metrics?.rmse?.toFixed(4) ?? "—"}</TableCell>
                        <TableCell className="text-sm font-mono text-right tabular-nums">{r.metrics?.mape?.toFixed(4) ?? "—"}</TableCell>
                        <TableCell className="text-sm font-mono text-right tabular-nums">{r.metrics?.r2?.toFixed(4) ?? "—"}</TableCell>
                        <TableCell className="text-sm font-mono text-right tabular-nums">{r.metrics?.aic?.toFixed(1) ?? "—"}</TableCell>
                        <TableCell className="text-sm font-mono text-right tabular-nums">{r.metrics?.bic?.toFixed(1) ?? "—"}</TableCell>
                        <TableCell className="text-sm font-mono text-right tabular-nums">{r.training_time?.toFixed(1) ?? "—"}</TableCell>
                        <TableCell className="text-center">{r.is_best && <CheckCircle2 className="w-4 h-4 text-primary mx-auto" />}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </motion.div>
    </motion.div>
  );
}
