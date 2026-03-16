import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useLocation } from "wouter";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { getWebSocketUrl } from "@/lib/queryClient";
import type { Job } from "@shared/schema";
import { AVAILABLE_MODELS } from "@shared/schema";
import {
  CheckCircle2, AlertCircle, Loader2, ArrowRight, Activity, Clock,
  BarChart2, BrainCircuit, Cpu, Hourglass, Layers, CircleDot,
} from "lucide-react";

interface ModelProgress {
  model: string;
  status: "pending" | "training" | "completed" | "failed";
  progress: number;
  message: string;
  metrics?: any;
  live_metrics?: any;
  training_time?: number;
}

// Map model id → category from the shared AVAILABLE_MODELS list
const MODEL_CATEGORY_MAP: Record<string, string> = Object.fromEntries(
  AVAILABLE_MODELS.map((m) => [m.id, m.category])
);

function ModelCategoryIcon({ modelId, className }: { modelId: string; className?: string }) {
  const cat = MODEL_CATEGORY_MAP[modelId] ?? "statistical";
  if (cat === "deep_learning") return <Cpu className={className} />;
  if (cat === "ml") return <BrainCircuit className={className} />;
  return <BarChart2 className={className} />;
}

// Pipeline stepper stages
type PipelineStage = "queued" | "preprocessing" | "training" | "completed" | "failed";

const STAGE_ORDER: PipelineStage[] = ["queued", "preprocessing", "training", "completed"];

function resolvePipelineStage(status: string): PipelineStage {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "training") return "training";
  if (status === "preprocessing") return "preprocessing";
  return "queued";
}

const STAGE_LABELS: Record<PipelineStage, string> = {
  queued: "Queued",
  preprocessing: "Preprocessing",
  training: "Training",
  completed: "Complete",
  failed: "Failed",
};

const STAGE_ICONS: Record<PipelineStage, React.FC<{ className?: string }>> = {
  queued: ({ className }) => <Hourglass className={className} />,
  preprocessing: ({ className }) => <Layers className={className} />,
  training: ({ className }) => <BrainCircuit className={className} />,
  completed: ({ className }) => <CheckCircle2 className={className} />,
  failed: ({ className }) => <AlertCircle className={className} />,
};

export default function TrainingPage() {
  const params = useParams<{ jobId: string }>();
  const [, navigate] = useLocation();
  const jobId = params.jobId || "";
  const [modelProgress, setModelProgress] = useState<Record<string, ModelProgress>>({});
  const [prepReport, setPrepReport] = useState<any>(null);
  const [overallStatus, setOverallStatus] = useState<string>("connecting");
  const [currentlyTrainingModel, setCurrentlyTrainingModel] = useState<string | null>(null);
  const [wsCompletedCount, setWsCompletedCount] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const wsRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsBackoffRef = useRef<number>(1000); // starts at 1s, doubles up to 30s

  const [wsConnected, setWsConnected] = useState(false);
  // FIX Bug 31: use a counter to trigger real reconnection (changes effect dependency)
  const wsReconnectCountRef = useRef(0);
  const [wsReconnectTick, setWsReconnectTick] = useState(0);
  // FIX Bug 32: use a ref for overallStatus so ws.onclose doesn't capture stale value
  const overallStatusRef = useRef<string>("connecting");
  const syncFromBackend = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["/api/jobs", jobId] });
    queryClient.invalidateQueries({ queryKey: ["/api/results", jobId] });
  }, [jobId, queryClient]);

  const { data: job } = useQuery<Job>({
    queryKey: ["/api/jobs", jobId],
    enabled: !!jobId,
    refetchOnWindowFocus: true,
    refetchInterval: overallStatus === "completed" || overallStatus === "failed" ? false : wsConnected ? 10000 : 3000,
  });

  // Keep overallStatusRef in sync with state so WS onclose can read current value without stale closure
  useEffect(() => {
    overallStatusRef.current = overallStatus;
  }, [overallStatus]);

  // Show error state if no jobId in URL or job not found after initial load
  if (!jobId) {
    return (
      <div className="flex items-center justify-center h-full p-6">
        <Card className="max-w-sm w-full">
          <CardContent className="py-10 flex flex-col items-center gap-3 text-center">
            <AlertCircle className="w-10 h-10 text-destructive" />
            <h2 className="text-sm font-semibold">No Job ID</h2>
            <p className="text-xs text-muted-foreground">The training page requires a valid job ID in the URL.</p>
            <Button size="sm" onClick={() => navigate("/")} className="mt-1">Go Home</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { data: resultsData } = useQuery<any>({
    queryKey: ["/api/results", jobId],
    enabled: !!jobId,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const results = query.state.data?.results || [];
      const total = job?.total_models || 0;
      if (job?.status !== "completed" && job?.status !== "failed") return wsConnected ? 10000 : 3000;
      if (total > 0 && results.length < total) return 2000;
      return false;
    },
  });

  // Pre-populate all selected models as "pending" as soon as we know the list
  useEffect(() => {
    const selected = job?.selected_models;
    if (!selected || selected.length === 0) return;
    setModelProgress((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const m of selected) {
        if (!next[m]) {
          next[m] = { model: m, status: "pending", progress: 0, message: "Waiting in queue..." };
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [job?.selected_models]);

  // WebSocket connection
  // FIX Bug 31: wsReconnectTick in deps causes this effect to re-run on reconnect
  useEffect(() => {
    if (!jobId) return;
    const wsUrl = getWebSocketUrl(jobId);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setOverallStatus("connected");
      setWsConnected(true);
      wsBackoffRef.current = 1000; // reset backoff on successful connection
      syncFromBackend();
    };
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case "status":
            setOverallStatus(msg.status);
            break;
          case "preprocessing":
            setPrepReport(msg.report);
            setOverallStatus("preprocessing");
            break;
          case "model_start":
            setCurrentlyTrainingModel(msg.model);
            if (msg.completed_count !== undefined) setWsCompletedCount(msg.completed_count);
            setModelProgress((prev) => ({
              ...prev,
              [msg.model]: { model: msg.model, status: "training", progress: 0, message: "Initializing model..." },
            }));
            setOverallStatus("training");
            break;
          case "model_progress":
            if (msg.currently_training) setCurrentlyTrainingModel(msg.currently_training);
            if (msg.completed_count !== undefined) setWsCompletedCount(msg.completed_count);
            setModelProgress((prev) => ({
              ...prev,
              [msg.model]: {
                ...prev[msg.model],
                model: msg.model,
                status: "training",
                progress: msg.progress * 100,
                message: msg.message,
                live_metrics: msg.live_metrics,
              },
            }));
            break;
          case "model_complete":
            setCurrentlyTrainingModel(null);
            if (msg.completed_count !== undefined) setWsCompletedCount(msg.completed_count);
            setModelProgress((prev) => ({
              ...prev,
              [msg.model]: {
                ...prev[msg.model],
                model: msg.model,
                status: "completed",
                progress: 100,
                message: "Completed",
                metrics: msg.metrics,
                training_time: msg.training_time,
              },
            }));
            queryClient.invalidateQueries({ queryKey: ["/api/results", jobId] });
            break;
          case "model_error":
            setCurrentlyTrainingModel(null);
            if (msg.completed_count !== undefined) setWsCompletedCount(msg.completed_count);
            setModelProgress((prev) => ({
              ...prev,
              [msg.model]: {
                ...prev[msg.model],
                model: msg.model,
                status: "failed",
                progress: 0,
                message: msg.error,
              },
            }));
            break;
          case "complete":
            setOverallStatus("completed");
            setCurrentlyTrainingModel(null);
            if (job?.total_models) setWsCompletedCount(job.total_models);
            queryClient.invalidateQueries({ queryKey: ["/api/results", jobId] });
            break;
          case "error":
            setOverallStatus("failed");
            setCurrentlyTrainingModel(null);
            break;
        }
      } catch { }
    };
    ws.onerror = () => setOverallStatus("error");
    ws.onclose = () => {
      setWsConnected(false);
      // FIX Bug 32: Read from ref to avoid stale closure
      const currentStatus = overallStatusRef.current;
      if (currentStatus !== "completed" && currentStatus !== "failed") {
        const delay = wsBackoffRef.current;
        wsBackoffRef.current = Math.min(delay * 2, 30_000);
        wsRetryRef.current = setTimeout(() => {
          // FIX Bug 31: Increment the tick to trigger the useEffect to run again and open a NEW WebSocket
          wsReconnectCountRef.current += 1;
          setWsReconnectTick((t) => t + 1);
        }, delay);
      }
    };

    return () => {
      if (wsRetryRef.current) clearTimeout(wsRetryRef.current);
      wsBackoffRef.current = 1000; // reset backoff on intentional close
      setWsConnected(false);
      ws.close();
    };
    // FIX Bug 31: wsReconnectTick in deps ensures a new WS is created on each reconnect trigger
  }, [jobId, syncFromBackend, wsReconnectTick]);

  // Polling fallback
  useEffect(() => {
    if (job) {
      if (job.status === "completed" || job.status === "failed") {
        setOverallStatus(job.status);
      } else {
        const currentIdx = STAGE_ORDER.indexOf(resolvePipelineStage(overallStatus));
        const jobIdx = STAGE_ORDER.indexOf(resolvePipelineStage(job.status));
        if (jobIdx > currentIdx) {
          setOverallStatus(job.status);
        } else if (overallStatus === "connecting" && job.status) {
          setOverallStatus(job.status);
        }
      }
      if (job.preprocessing_report) {
        setPrepReport(job.preprocessing_report);
      }
      if (wsCompletedCount === null && job.completed_models !== undefined) {
        setWsCompletedCount(job.completed_models);
      }
    }

    if (resultsData?.results?.length) {
      setModelProgress((prev) => {
        const next = { ...prev };
        let updated = false;
        resultsData.results.forEach((r: any) => {
          if (!next[r.model_name] || next[r.model_name].status !== r.status || !next[r.model_name].metrics) {
            next[r.model_name] = {
              model: r.model_name,
              status: r.status as any,
              progress: r.status === "completed" ? 100 : r.status === "failed" ? 0 : 50,
              message: r.error || (r.status === "completed" ? "Completed" : "Processing..."),
              metrics: r.metrics,
              training_time: r.training_time,
            };
            updated = true;
          }
        });
        return updated ? next : prev;
      });
    }
  }, [job, resultsData]);

  useEffect(() => {
    if (job?.status === "completed" && Object.keys(modelProgress).length === job?.total_models && job?.total_models > 0) {
      setOverallStatus("completed");
    }
  }, [job, modelProgress]);

  const models = Object.values(modelProgress);
  const totalCount = job?.total_models || models.length || 0;
  // FIX Bug 33: Prefer wsCompletedCount (real-time) over polling; fall back to DB count then model count
  const completedCount = overallStatus === "completed"
    ? totalCount
    : (wsCompletedCount !== null
      ? wsCompletedCount
      : Math.max(
        job?.completed_models || 0,
        models.filter((m) => m.status === "completed" || m.status === "failed").length
      ));
  const progressPercent = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

  const pipelineStage = resolvePipelineStage(overallStatus);
  const currentStageIndex = pipelineStage === "failed"
    ? -1
    : STAGE_ORDER.indexOf(pipelineStage);

  // Ordered list of models to display (preserve selected_models order if available)
  const orderedModels: ModelProgress[] = job?.selected_models
    ? job.selected_models.map((id) => modelProgress[id] ?? { model: id, status: "pending", progress: 0, message: "Waiting in queue..." })
    : models;

  const containerVariants = {
    hidden: { opacity: 0 },
    show: { opacity: 1, transition: { staggerChildren: 0.08 } },
  };
  const itemVariants = {
    hidden: { opacity: 0, y: 15 },
    show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } },
  };

  return (
    <motion.div initial="hidden" animate="show" variants={containerVariants} className="p-6 max-w-7xl mx-auto space-y-6">
      <Breadcrumbs items={[{ label: "Home", href: "/" }, { label: "Training" }, { label: jobId }]} />

      {/* Header */}
      <motion.div variants={itemVariants} className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Training Pipeline</h1>
        {overallStatus === "completed" && (
          <Button onClick={() => navigate(`/results/${jobId}`)} className="gap-1.5" data-testid="btn-view-results">
            View Results <ArrowRight className="w-4 h-4" />
          </Button>
        )}
      </motion.div>

      {/* Pipeline Stepper */}
      <motion.div variants={itemVariants}>
        <Card className="glass-card">
          <CardContent className="py-4">
            <div className="flex items-center gap-0 overflow-x-auto">
              {STAGE_ORDER.map((stage, idx) => {
                const Icon = STAGE_ICONS[pipelineStage === "failed" ? "failed" : stage];
                const isActive = idx === currentStageIndex && pipelineStage !== "completed";
                const isDone = idx < currentStageIndex || pipelineStage === "completed";
                const isFailed = pipelineStage === "failed" && idx === currentStageIndex;
                return (
                  <div key={stage} className="flex items-center flex-1 min-w-0">
                    <div className={`flex flex-col items-center gap-1.5 px-3 flex-shrink-0 ${isActive && !isFailed ? "text-primary" :
                      isDone ? "text-green-500" :
                        isFailed ? "text-destructive" :
                          "text-muted-foreground/50"
                      }`}>
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center border-2 transition-all shadow-sm ${isActive && !isFailed ? "border-primary bg-primary/10" :
                        isDone ? "border-green-500 bg-green-500/10" :
                          isFailed ? "border-destructive bg-destructive/10" :
                            "border-muted-foreground/20 bg-muted/40"
                        }`}>
                        {isActive && !isFailed
                          ? <Loader2 className="w-4 h-4 animate-spin" />
                          : isDone
                            ? <CheckCircle2 className="w-4 h-4" />
                            : <Icon className="w-4 h-4" />
                        }
                      </div>
                      <span className="text-[11px] font-medium whitespace-nowrap">{STAGE_LABELS[stage]}</span>
                    </div>
                    {idx < STAGE_ORDER.length - 1 && (
                      <div className={`flex-1 h-0.5 mx-1.5 rounded-full transition-all ${idx < currentStageIndex || pipelineStage === "completed"
                        ? "bg-green-500"
                        : "bg-muted-foreground/20"
                        }`} />
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Overall Progress */}
      <motion.div variants={itemVariants}>
        <Card className="glass-card relative overflow-hidden">
          {overallStatus === "training" && (
            <div className="absolute inset-0 bg-primary/20 backdrop-blur-3xl animate-pulse-slow z-0"></div>
          )}
          <CardContent className="py-4 relative z-10">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {overallStatus === "completed" ? (
                  <CheckCircle2 className="w-5 h-5 text-green-500" />
                ) : overallStatus === "failed" ? (
                  <AlertCircle className="w-5 h-5 text-destructive" />
                ) : (
                  <Loader2 className="w-5 h-5 text-primary animate-spin" />
                )}
                <span className="text-sm font-medium">
                  {overallStatus === "completed"
                    ? "All models completed"
                    : overallStatus === "preprocessing"
                      ? "Preprocessing data..."
                      : overallStatus === "failed"
                        ? "Training failed"
                        : overallStatus === "training"
                          ? currentlyTrainingModel
                            ? `Training ${currentlyTrainingModel}...`
                            : "Training models..."
                          : overallStatus === "queued"
                            ? "Job queued for processing..."
                            : overallStatus === "connected"
                              ? "Waiting for training to begin..."
                              : "Connecting to training server..."}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {currentlyTrainingModel && (
                  <Badge variant="secondary" className="text-[10px] animate-pulse bg-primary/10 text-primary border-primary/20">
                    <CircleDot className="w-2.5 h-2.5 mr-1" />
                    {currentlyTrainingModel}
                  </Badge>
                )}
                {(overallStatus === "training" || overallStatus === "completed" || overallStatus === "failed") && (
                  <Badge variant={overallStatus === "completed" ? "default" : "outline"} className="text-xs tabular-nums">
                    {completedCount} / {totalCount}
                  </Badge>
                )}
              </div>
            </div>
            {(overallStatus === "training" || overallStatus === "completed" || overallStatus === "failed") && (
              <Progress
                value={progressPercent}
                className={`h-2 transition-all duration-500 ${overallStatus === "training" ? "progress-stripe" : ""}`}
              />
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* Preprocessing Report */}
      {prepReport && (
        <motion.div variants={itemVariants}>
          <Card className="glass-card">
            <CardContent className="py-4">
              <h3 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <Activity className="w-4 h-4" /> Preprocessing Report
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div className="bg-muted/50 rounded-md p-2.5">
                  <p className="text-muted-foreground">Rows</p>
                  <p className="font-semibold text-sm tabular-nums">{prepReport.final_shape?.[0] ?? "—"}</p>
                </div>
                <div className="bg-muted/50 rounded-md p-2.5">
                  <p className="text-muted-foreground">Frequency</p>
                  <p className="font-semibold text-sm">{prepReport.detected_frequency ?? "—"}</p>
                </div>
                <div className="bg-muted/50 rounded-md p-2.5">
                  <p className="text-muted-foreground">Stationary</p>
                  <p className="font-semibold text-sm">{prepReport.stationarity?.is_stationary ? "Yes" : "No"}</p>
                </div>
                <div className="bg-muted/50 rounded-md p-2.5">
                  <p className="text-muted-foreground">Seasonal</p>
                  <p className="font-semibold text-sm">{prepReport.seasonality?.detected ? "Yes" : "No"}</p>
                </div>
              </div>
              {prepReport.steps && prepReport.steps.length > 0 && (
                <div className="mt-3 space-y-1">
                  {prepReport.steps.map((s: any, i: number) => (
                    <div key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <CheckCircle2 className="w-3 h-3 text-green-500 shrink-0" />
                      <span>{s.step?.replace(/_/g, " ")}</span>
                      {s.frequency && <Badge variant="outline" className="text-[10px] px-1 py-0">{s.frequency}</Badge>}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Model Progress Cards */}
      <motion.div variants={containerVariants} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {orderedModels.map((m) => (
          <motion.div key={m.model} variants={itemVariants}>
            <Card className={`transition-all duration-500 h-full backdrop-blur-md ${m.status === "completed" ? "border-green-500/30 bg-green-500/5 shadow-[0_0_15px_rgba(34,197,94,0.1)]" :
              m.status === "failed" ? "border-destructive/30 bg-destructive/5" :
                m.status === "training" ? "border-primary/50 bg-primary/10 shadow-[0_0_20px_rgba(var(--primary),0.2)] scale-[1.02]" :
                  "border-border/40 bg-card/40 opacity-70"
              }`}>
              <CardContent className="py-4">
                {/* Card header */}
                <div className="flex items-center justify-between mb-2.5">
                  <div className="flex items-center gap-2">
                    {/* Status icon */}
                    {m.status === "completed" ? (
                      <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
                    ) : m.status === "failed" ? (
                      <AlertCircle className="w-4 h-4 text-destructive shrink-0" />
                    ) : m.status === "training" ? (
                      <Loader2 className="w-4 h-4 text-primary animate-spin shrink-0" />
                    ) : (
                      <Hourglass className="w-4 h-4 text-muted-foreground/50 shrink-0" />
                    )}

                    {/* Model category icon */}
                    <ModelCategoryIcon
                      modelId={m.model}
                      className={`w-3.5 h-3.5 shrink-0 ${m.status === "completed" ? "text-green-500" :
                        m.status === "training" ? "text-primary" :
                          "text-muted-foreground/50"
                        }`}
                    />

                    <span className="text-sm font-semibold">{m.model}</span>

                    {/* Category badge */}
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 hidden sm:inline-flex">
                      {MODEL_CATEGORY_MAP[m.model] === "deep_learning"
                        ? "Deep Learning"
                        : MODEL_CATEGORY_MAP[m.model] === "ml"
                          ? "ML"
                          : "Statistical"}
                    </Badge>
                  </div>

                  {m.training_time != null ? (
                    <span className="text-xs text-muted-foreground flex items-center gap-1 tabular-nums">
                      <Clock className="w-3 h-3" /> {m.training_time.toFixed(1)}s
                    </span>
                  ) : m.status === "pending" ? (
                    <Badge variant="outline" className="text-[10px] text-muted-foreground">Queued</Badge>
                  ) : m.status === "training" ? (
                    <Badge variant="outline" className="text-[10px] text-primary border-primary/30 animate-pulse">
                      {m.progress > 0 ? `${Math.round(m.progress)}%` : "Starting..."}
                    </Badge>
                  ) : null}
                </div>

                {/* Training progress bar + live message */}
                {m.status === "training" && (
                  <div className="space-y-1.5 mt-2">
                    <Progress value={m.progress} className="h-1.5" />
                    <p className="text-[11px] text-muted-foreground leading-tight truncate">{m.message}</p>
                    {/* LSTM/Transformer live epoch metrics */}
                    {m.live_metrics && (
                      <div className="flex items-center justify-between text-[10px] text-muted-foreground bg-muted/40 rounded px-2 py-1 mt-1">
                        <span>Epoch {m.live_metrics.epoch}</span>
                        {m.live_metrics.loss != null && (
                          <span className="font-mono">Loss: {m.live_metrics.loss.toFixed(4)}</span>
                        )}
                        {m.live_metrics.val_loss != null && (
                          <span className="font-mono">Val: {m.live_metrics.val_loss.toFixed(4)}</span>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Completed metrics */}
                {m.metrics && (
                  <div className="grid grid-cols-4 gap-2 mt-2.5">
                    {[
                      { label: "MAE", value: m.metrics.mae },
                      { label: "RMSE", value: m.metrics.rmse },
                      { label: "MAPE", value: m.metrics.mape },
                      { label: "R²", value: m.metrics.r2 },
                    ].map((metric) => (
                      <div key={metric.label} className="text-center">
                        <p className="text-[10px] text-muted-foreground">{metric.label}</p>
                        <p className="text-xs font-semibold font-mono tabular-nums">
                          {metric.value != null ? Number(metric.value).toFixed(3) : "—"}
                        </p>
                      </div>
                    ))}
                  </div>
                )}

                {/* Failed error message */}
                {m.status === "failed" && (
                  <p className="text-xs text-destructive mt-1.5 truncate">{m.message}</p>
                )}
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </motion.div>
    </motion.div>
  );
}
