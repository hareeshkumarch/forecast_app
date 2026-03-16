import { useState, useCallback, useRef } from "react";
import { useLocation } from "wouter";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiRequest, sessionStore, getApiBase } from "@/lib/queryClient";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Slider } from "@/components/ui/slider";
import { useToast } from "@/hooks/use-toast";
import {
  Upload, Database, FileSpreadsheet, ArrowRight, Sparkles,
  BarChart3, Brain, Cpu, Play, ArrowUpRight, ChevronRight, Columns, AlertTriangle, Settings2,
  ShieldCheck, Info, TrendingUp, CalendarClock, AlertCircle
} from "lucide-react";
import { AVAILABLE_MODELS } from "@shared/schema";
import type { ColumnDetection, DemoDataset } from "@shared/schema";

export default function HomePage() {
  const [, navigate] = useLocation();
  const { toast } = useToast();
  const [step, setStep] = useState<"upload" | "configure">("upload");
  const [detection, setDetection] = useState<ColumnDetection | null>(null);
  const [dateCol, setDateCol] = useState("");
  const [targetCol, setTargetCol] = useState("");
  const [exogCols, setExogCols] = useState<string[]>([]);
  const [frequency, setFrequency] = useState("auto");
  const [horizon, setHorizon] = useState(30);
  const [selectedModels, setSelectedModels] = useState<string[]>(["ARIMA", "Prophet", "Holt-Winters"]);
  const [cleanAnomalies, setCleanAnomalies] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Pro Mode Hyperparameters consolidated into one state
  const [autoTune, setAutoTune] = useState(false);
  const [hp, setHp] = useState({
    lstmEpochs: 50,
    transformerEpochs: 50,
    prophetCps: 0.05,
    arimaP: 1, arimaD: 1, arimaQ: 1,
    sarimaP: 1, sarimaQ: 1,
    hwTrend: "add" as "add" | "mul", hwSeasonal: "add" as "add" | "mul"
  });

  const updateHp = (key: keyof typeof hp, value: any) => setHp(prev => ({ ...prev, [key]: value }));

  const [uploading, setUploading] = useState(false);

  const { data: demos } = useQuery<DemoDataset[]>({ queryKey: ["/api/demos"] });

  const forecastMutation = useMutation({
    mutationFn: async (config: any) => {
      const res = await apiRequest("POST", "/api/forecast", config);
      return res.json();
    },
    onSuccess: (data) => {
      sessionStore.setJobId(data.job_id);
      navigate(`/training/${data.job_id}`);
    },
    onError: (err: any) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  const handleFileUpload = useCallback(async (file: File) => {
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${getApiBase()}/api/upload`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(await res.text());
      const data: ColumnDetection = await res.json();
      setDetection(data);
      if (data.date_col) setDateCol(data.date_col);
      if (data.target_col) setTargetCol(data.target_col);
      // FIX Bug 21: Default exogCols to [] — user must explicitly opt-in to avoid overfitting
      setExogCols([]);
      setStep("configure");
    } catch (e: any) {
      toast({ title: "Upload failed", description: e.message, variant: "destructive" });
    } finally {
      setUploading(false);
    }
  }, [toast]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  }, [handleFileUpload]);

  const handleDemoSelect = useCallback(async (demoId: string) => {
    setUploading(true);
    try {
      const res = await fetch(`${getApiBase()}/api/demo/${demoId}`);
      if (!res.ok) throw new Error(await res.text());
      const data: ColumnDetection = await res.json();
      setDetection(data);
      if (data.date_col) setDateCol(data.date_col);
      if (data.target_col) setTargetCol(data.target_col);
      // FIX Bug 21: Same as file upload — default exog to empty
      setExogCols([]);
      setStep("configure");
    } catch (e: any) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setUploading(false);
    }
  }, [toast]);

  const handleStartForecast = () => {
    if (!detection || !dateCol || !targetCol || selectedModels.length === 0) {
      toast({ title: "Missing fields", description: "Select date column, target column, and at least one model", variant: "destructive" });
      return;
    }
    // FIX Bug 23: Validate that date and target columns are not the same
    if (dateCol === targetCol) {
      toast({ title: "Invalid selection", description: "Date column and target column cannot be the same", variant: "destructive" });
      return;
    }
    forecastMutation.mutate({
      filename: detection.filename,
      original_filename: detection.original_filename,
      date_col: dateCol,
      target_col: targetCol,
      exog_cols: exogCols,
      frequency,
      horizon,
      selected_models: selectedModels,
      clean_anomalies: cleanAnomalies,
      auto_tune: autoTune,
      hyperparameters: {
        lstm_epochs: hp.lstmEpochs,
        transformer_epochs: hp.transformerEpochs,
        prophet_cps: hp.prophetCps,
        arima_p: hp.arimaP,
        arima_d: hp.arimaD,
        arima_q: hp.arimaQ,
      }
    });
  };

  const toggleModel = (id: string) => {
    setSelectedModels((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]
    );
  };

  if (step === "configure" && detection) {
    return (
      <div className="p-6 max-w-7xl mx-auto space-y-6 animate-fade-in">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Configure Forecast</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              {detection.original_filename} — {detection.shape[0]} rows, {detection.shape[1]} columns
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => { setStep("upload"); setDetection(null); }} data-testid="btn-back">
            Change data
          </Button>
        </div>

        {/* Column Intelligence Panel */}
        {detection.column_mapping && (
          <Card className="glass-card border-primary/30 bg-primary/5 relative overflow-hidden">
            <div className="absolute -right-10 -top-10 w-32 h-32 bg-primary/10 blur-3xl rounded-full pointer-events-none"></div>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2 text-primary">
                <ShieldCheck className="w-4 h-4" /> Column Intelligence
              </CardTitle>
              <CardDescription className="text-xs">
                We automatically analyzed your data and mapped the most likely columns
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Auto-detection summary */}
              <div className="flex flex-wrap gap-2">
                {detection.column_mapping["date"] && (
                  <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-muted border text-xs">
                    <CalendarClock className="w-3.5 h-3.5 text-blue-500" />
                    <span className="text-muted-foreground">Date:</span>
                    <span className="font-semibold font-mono">{detection.column_mapping["date"]}</span>
                    {detection.mapping_confidence?.[detection.column_mapping["date"]] != null && (
                      <span className={`ml-1 font-bold tabular-nums ${(detection.mapping_confidence[detection.column_mapping["date"]] ?? 0) >= 80
                        ? "text-green-600"
                        : (detection.mapping_confidence[detection.column_mapping["date"]] ?? 0) >= 50
                          ? "text-yellow-600"
                          : "text-red-500"
                        }`}>
                        {detection.mapping_confidence[detection.column_mapping["date"]]}%
                      </span>
                    )}
                  </div>
                )}
                {detection.column_mapping["target"] && (
                  <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-muted border text-xs">
                    <TrendingUp className="w-3.5 h-3.5 text-violet-500" />
                    <span className="text-muted-foreground">Target:</span>
                    <span className="font-semibold font-mono">{detection.column_mapping["target"]}</span>
                    {detection.mapping_confidence?.[detection.column_mapping["target"]] != null && (
                      <span className={`ml-1 font-bold tabular-nums ${(detection.mapping_confidence[detection.column_mapping["target"]] ?? 0) >= 80
                        ? "text-green-600"
                        : (detection.mapping_confidence[detection.column_mapping["target"]] ?? 0) >= 50
                          ? "text-yellow-600"
                          : "text-red-500"
                        }`}>
                        {detection.mapping_confidence[detection.column_mapping["target"]]}%
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Mapping warnings */}
              {detection.mapping_warnings && detection.mapping_warnings.length > 0 && (
                <div className="space-y-1.5">
                  {detection.mapping_warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs text-yellow-700 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950/40 border border-yellow-200 dark:border-yellow-800/50 rounded-md px-2.5 py-1.5">
                      <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      <span>{w}</span>
                    </div>
                  ))}
                </div>
              )}

              <p className="text-[10px] text-muted-foreground flex items-center gap-1">
                <Info className="w-3 h-3" />
                You can override the selections below
              </p>
            </CardContent>
          </Card>
        )}

        {/* Column Mapping */}
        <Card className="glass-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Columns className="w-4 h-4" /> Column Mapping
            </CardTitle>
            <CardDescription className="text-xs">Confirm or override the auto-detected column assignments</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Date Column</Label>
                <Select value={dateCol} onValueChange={setDateCol}>
                  <SelectTrigger data-testid="select-date-col"><SelectValue placeholder="Select date column" /></SelectTrigger>
                  <SelectContent>
                    {detection.all_columns.map((c) => {
                      const conf = detection.mapping_confidence?.[c];
                      return (
                        <SelectItem key={c} value={c}>
                          <span className="flex items-center gap-2">
                            {c}
                            {conf != null && conf > 0 && (
                              <span className={`text-[10px] font-bold ml-1 ${conf >= 80 ? "text-green-600" : conf >= 50 ? "text-yellow-600" : "text-red-500"
                                }`}>
                                {conf}%
                              </span>
                            )}
                          </span>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Target Column</Label>
                <Select value={targetCol} onValueChange={setTargetCol}>
                  <SelectTrigger data-testid="select-target-col"><SelectValue placeholder="Select target column" /></SelectTrigger>
                  <SelectContent>
                    {detection.numeric_columns.map((c) => {
                      const conf = detection.mapping_confidence?.[c];
                      return (
                        <SelectItem key={c} value={c}>
                          <span className="flex items-center gap-2">
                            {c}
                            {conf != null && conf > 0 && (
                              <span className={`text-[10px] font-bold ml-1 ${conf >= 80 ? "text-green-600" : conf >= 50 ? "text-yellow-600" : "text-red-500"
                                }`}>
                                {conf}%
                              </span>
                            )}
                          </span>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {detection.numeric_columns.filter((c) => c !== targetCol).length > 0 && (
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Exogenous Variables (optional)</Label>
                <div className="flex flex-wrap gap-2">
                  {detection.numeric_columns.filter((c) => c !== targetCol).map((c) => (
                    <label key={c} className="flex items-center gap-1.5 text-xs cursor-pointer">
                      <Checkbox
                        checked={exogCols.includes(c)}
                        onCheckedChange={(checked) => {
                          setExogCols((prev) => checked ? [...prev, c] : prev.filter((x) => x !== c));
                        }}
                      />
                      {c}
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Data preview */}
            {detection.preview && detection.preview.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-muted-foreground mb-2">Data preview (first 5 rows)</p>
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-muted/50">
                        {Object.keys(detection.preview[0]).map((k) => (
                          <th key={k} className="px-3 py-1.5 text-left font-medium text-muted-foreground">{k}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {detection.preview.map((row, i) => (
                        <tr key={i} className="border-t border-border/50">
                          {Object.values(row).map((v: any, j) => (
                            <td key={j} className="px-3 py-1.5 font-mono">{v != null ? String(v).slice(0, 20) : "—"}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Forecast Settings */}
        <Card className="glass-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Sparkles className="w-4 h-4" /> Forecast Settings
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Frequency</Label>
                <Select value={frequency} onValueChange={setFrequency}>
                  <SelectTrigger data-testid="select-frequency"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Auto-detect</SelectItem>
                    <SelectItem value="D">Daily</SelectItem>
                    <SelectItem value="W">Weekly</SelectItem>
                    <SelectItem value="MS">Monthly</SelectItem>
                    <SelectItem value="QS">Quarterly</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Forecast Horizon</Label>
                {/* FIX Bug 24: Cap horizon relative to detected frequency */}
                {(() => {
                  const freqMaxMap: Record<string, number> = { H: 168, "6H": 60, D: 365, B: 260, W: 104, "2W": 52, MS: 60, QS: 20, YS: 10 };
                  const maxHorizon = freqMaxMap[frequency] ?? 365;
                  return (
                    <Input
                      type="number"
                      min={1}
                      max={maxHorizon}
                      value={Math.min(horizon, maxHorizon)}
                      onChange={(e) => setHorizon(Math.min(Number(e.target.value), maxHorizon))}
                      data-testid="input-horizon"
                    />
                  );
                })()}
                {frequency !== "auto" && (
                  <p className="text-[10px] text-muted-foreground">
                    Max for {frequency} frequency: {({ H: 168, "6H": 60, D: 365, B: 260, W: 104, "2W": 52, MS: 60, QS: 20, YS: 10 } as any)[frequency] ?? 365} steps
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Anomaly Detection */}
        {(detection as any).anomalies && (detection as any).anomalies.length > 0 && (
          <Card className="border-destructive/40 bg-destructive/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-destructive flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" /> Outliers Detected
              </CardTitle>
              <CardDescription className="text-xs text-destructive/80">
                We found {(detection as any).anomalies.length} potential anomalies or spikes in your target data.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                <Checkbox
                  checked={cleanAnomalies}
                  onCheckedChange={(checked) => setCleanAnomalies(!!checked)}
                />
                Automatically smooth anomalies before training
              </label>
            </CardContent>
          </Card>
        )}

        {/* Model Selection */}
        <Card className="glass-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Brain className="w-4 h-4" /> Model Selection
            </CardTitle>
            <CardDescription className="text-xs">{selectedModels.length} of {AVAILABLE_MODELS.length} models selected</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {AVAILABLE_MODELS.map((model) => {
                const isSelected = selectedModels.includes(model.id);
                return (
                  <div
                    key={model.id}
                    className={`flex items-start gap-2.5 p-3 rounded-md border cursor-pointer transition-all duration-300 ${isSelected
                      ? "border-primary bg-primary/10 shadow-[0_0_15px_rgba(var(--primary),0.15)] scale-[1.02]"
                      : "border-border/50 hover:border-primary/40 hover:bg-card/80"
                      }`}
                    onClick={() => toggleModel(model.id)}
                    data-testid={`model-${model.id}`}
                  >
                    <Checkbox checked={isSelected} className="mt-0.5" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium">{model.name}</span>
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          {model.category === "deep_learning" ? "DL" : model.category === "ml" ? "ML" : "Stat"}
                        </Badge>
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5 leading-tight">{model.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* Pro Mode Configuration */}
        <Accordion type="single" collapsible className="w-full">
          <AccordionItem value="pro-mode" className="border rounded-lg bg-card text-card-foreground shadow-sm px-4">
            <AccordionTrigger className="hover:no-underline py-4">
              <div className="flex items-center gap-2">
                <Settings2 className="w-4 h-4 text-primary" />
                <span className="text-sm font-semibold">Advanced Setup (Pro)</span>
              </div>
            </AccordionTrigger>
            <AccordionContent className="pt-2 pb-4 space-y-6">
              {/* Auto-Tune Toggle */}
              <div className="flex items-start space-x-3 bg-primary/5 p-4 rounded-md border border-primary/20">
                <Checkbox id="auto-tune" checked={autoTune} onCheckedChange={(c) => setAutoTune(!!c)} className="mt-0.5" />
                <div className="grid gap-1.5 leading-none">
                  <label htmlFor="auto-tune" className="text-sm font-medium cursor-pointer">
                    Auto-Tune Hyperparameters
                  </label>
                  <p className="text-[11px] text-muted-foreground leading-snug">
                    Automatically search for the optimal configuration for each model. This will ignore the manual settings below and may significantly increase training time, but usually yields better results.
                  </p>
                </div>
              </div>

              <div className={`space-y-6 transition-opacity ${autoTune ? "opacity-40 pointer-events-none grayscale" : ""}`}>
                {/* LSTM Settings */}
                {(selectedModels.includes("LSTM")) && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs font-medium">LSTM Training Epochs</Label>
                      <span className="text-xs text-muted-foreground">{hp.lstmEpochs}</span>
                    </div>
                    <Slider
                      value={[hp.lstmEpochs]}
                      min={5} max={200} step={5}
                      onValueChange={(v) => updateHp("lstmEpochs", v[0])}
                    />
                    <p className="text-[10px] text-muted-foreground">Higher epochs may improve LSTM accuracy but increase training time.</p>
                  </div>
                )}

                {/* Transformer Settings */}
                {selectedModels.includes("Transformer") && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs font-medium">Transformer Training Epochs</Label>
                      <span className="text-xs text-muted-foreground">{hp.transformerEpochs}</span>
                    </div>
                    <Slider
                      value={[hp.transformerEpochs]}
                      min={5} max={200} step={5}
                      onValueChange={(v) => updateHp("transformerEpochs", v[0])}
                    />
                    <p className="text-[10px] text-muted-foreground">Higher epochs may improve Transformer accuracy but increase training time.</p>
                  </div>
                )}

                {/* Prophet Settings */}
                {selectedModels.includes("Prophet") && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs font-medium">Prophet Changepoint Prior Scale</Label>
                      <span className="text-xs text-muted-foreground">{hp.prophetCps}</span>
                    </div>
                    <Slider
                      value={[hp.prophetCps]}
                      min={0.01} max={0.5} step={0.01}
                      onValueChange={(v) => updateHp("prophetCps", v[0])}
                    />
                    <p className="text-[10px] text-muted-foreground">Adjusts trend flexibility. Higher values can overfit, lower values can underfit.</p>
                  </div>
                )}

                {/* ARIMA Settings */}
                {selectedModels.includes("ARIMA") && (
                  <div className="space-y-3">
                    <Label className="text-xs font-medium">ARIMA Order (p, d, q)</Label>
                    <div className="flex gap-4">
                      <div className="space-y-1.5 flex-1">
                        <Label className="text-[10px] text-muted-foreground">AR (p)</Label>
                        <Input type="number" min={0} max={5} value={hp.arimaP} onChange={(e) => updateHp("arimaP", Number(e.target.value))} className="h-8 text-xs" />
                      </div>
                      <div className="space-y-1.5 flex-1">
                        <Label className="text-[10px] text-muted-foreground">Diff (d)</Label>
                        <Input type="number" min={0} max={2} value={hp.arimaD} onChange={(e) => updateHp("arimaD", Number(e.target.value))} className="h-8 text-xs" />
                      </div>
                      <div className="space-y-1.5 flex-1">
                        <Label className="text-[10px] text-muted-foreground">MA (q)</Label>
                        <Input type="number" min={0} max={5} value={hp.arimaQ} onChange={(e) => updateHp("arimaQ", Number(e.target.value))} className="h-8 text-xs" />
                      </div>
                    </div>
                    <p className="text-[10px] text-muted-foreground">Manually override the auto-correlation parameters.</p>
                  </div>
                )}

                {/* FIX Bug 25: SARIMA Settings */}
                {selectedModels.includes("SARIMA") && (
                  <div className="space-y-3">
                    <Label className="text-xs font-medium">SARIMA Seasonal Order (P, Q)</Label>
                    <div className="flex gap-4">
                      <div className="space-y-1.5 flex-1">
                        <Label className="text-[10px] text-muted-foreground">Seasonal AR (P)</Label>
                        <Input type="number" min={0} max={2} value={hp.sarimaP} onChange={(e) => updateHp("sarimaP", Number(e.target.value))} className="h-8 text-xs" />
                      </div>
                      <div className="space-y-1.5 flex-1">
                        <Label className="text-[10px] text-muted-foreground">Seasonal MA (Q)</Label>
                        <Input type="number" min={0} max={2} value={hp.sarimaQ} onChange={(e) => updateHp("sarimaQ", Number(e.target.value))} className="h-8 text-xs" />
                      </div>
                    </div>
                    <p className="text-[10px] text-muted-foreground">Seasonal p and q order. Seasonal period (m) is auto-detected from data frequency.</p>
                  </div>
                )}

                {/* FIX Bug 25: Holt-Winters Settings */}
                {selectedModels.includes("Holt-Winters") && (
                  <div className="space-y-3">
                    <Label className="text-xs font-medium">Holt-Winters Component Types</Label>
                    <div className="flex gap-4">
                      <div className="space-y-1.5 flex-1">
                        <Label className="text-[10px] text-muted-foreground">Trend</Label>
                        <Select value={hp.hwTrend} onValueChange={(v) => updateHp("hwTrend", v)}>
                          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="add">Additive</SelectItem>
                            <SelectItem value="mul">Multiplicative</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5 flex-1">
                        <Label className="text-[10px] text-muted-foreground">Seasonal</Label>
                        <Select value={hp.hwSeasonal} onValueChange={(v) => updateHp("hwSeasonal", v)}>
                          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="add">Additive</SelectItem>
                            <SelectItem value="mul">Multiplicative</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <p className="text-[10px] text-muted-foreground">Additive is better when seasonality amplitude is constant; multiplicative when it grows with the level.</p>
                  </div>
                )}

                {!selectedModels.includes("LSTM") && !selectedModels.includes("Transformer") && !selectedModels.includes("Prophet") && !selectedModels.includes("ARIMA") && !selectedModels.includes("SARIMA") && !selectedModels.includes("Holt-Winters") && (
                  <p className="text-xs text-muted-foreground italic">No advanced settings available for the currently selected models.</p>
                )}
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        {/* Start Button */}
        <div className="flex justify-end">
          <Button
            onClick={handleStartForecast}
            disabled={forecastMutation.isPending || !dateCol || !targetCol || selectedModels.length === 0}
            className="gap-2"
            data-testid="btn-start-forecast"
          >
            {forecastMutation.isPending ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Start Training
          </Button>
        </div>
      </div>
    );
  }

  const lastJobId = sessionStore.getJobId();

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight gradient-text mb-1">New Forecast</h1>
          <p className="text-sm text-muted-foreground mt-0.5 font-medium">Upload your time series data or try an interactive demo dataset</p>
        </div>
        {lastJobId && (
          <Button variant="outline" size="sm" onClick={() => navigate(`/results/${lastJobId}`)} className="gap-1.5 bg-primary/5 border-primary/20 text-primary hover:bg-primary/10">
            <ArrowUpRight className="w-3.5 h-3.5" /> View Last Job {lastJobId.slice(0, 8)}
          </Button>
        )}
      </div>

      {/* Upload Zone */}
      <Card className="glass-card overflow-hidden border-0 relative">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-chart-2/5 animate-pulse-slow"></div>
        <CardContent className="pt-6 relative z-10">
          {/* Hidden accessible file input — receives focus from keyboard, reads by screen readers */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="sr-only"
            aria-label="Upload CSV or Excel file"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileUpload(file);
              e.target.value = "";
            }}
          />
          <div
            role="button"
            tabIndex={0}
            aria-label="Drop your file here or click to browse"
            className={`border-2 border-dashed rounded-xl p-12 text-center transition-all duration-300 cursor-pointer relative group ${uploading ? "border-primary bg-primary/10 scale-[0.98]" : "border-primary/30 hover:border-primary hover:bg-primary/5 hover:shadow-[0_0_30px_rgba(var(--primary),0.15)]"
              }`}
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInputRef.current?.click(); } }}
            data-testid="upload-zone"
          >
            {uploading ? (
              <div className="flex flex-col items-center gap-4">
                <div className="relative">
                  <div className="absolute inset-0 bg-primary/20 blur-xl rounded-full animate-pulse"></div>
                  <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin relative z-10" />
                </div>
                <p className="text-base font-semibold text-primary animate-pulse">Processing file...</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-4">
                <div className="relative group-hover:-translate-y-2 transition-transform duration-500 ease-out">
                  <div className="absolute inset-0 bg-primary/20 blur-xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-500"></div>
                  <div className="w-16 h-16 rounded-full bg-primary/10 text-primary flex items-center justify-center relative z-10 shadow-inner border border-primary/20 group-hover:bg-primary/20 transition-colors">
                    <Upload className="w-7 h-7" />
                  </div>
                </div>
                <div>
                  <p className="text-base font-semibold">Drop your file here or <span className="text-primary hover:underline">click to browse</span></p>
                  <p className="text-xs text-muted-foreground mt-1.5 font-medium">CSV, Excel (.xlsx, .xls) up to 50MB</p>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Separator className="flex-1" />
        <span className="text-xs text-muted-foreground">or try a demo</span>
        <Separator className="flex-1" />
      </div>

      {/* Demo Datasets */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {(demos || []).map((demo) => (
          <Card
            key={demo.id}
            className="glass-card cursor-pointer group"
            onClick={() => handleDemoSelect(demo.id)}
            data-testid={`demo-${demo.id}`}
          >
            <CardContent className="pt-4 pb-4">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <Database className="w-4 h-4 text-primary shrink-0" />
                  <h3 className="text-sm font-medium leading-tight">{demo.name}</h3>
                </div>
                <ChevronRight className="w-3.5 h-3.5 text-muted-foreground group-hover:text-primary transition-colors shrink-0" />
              </div>
              <p className="text-[11px] text-muted-foreground mt-1.5 leading-snug">{demo.description}</p>
              <div className="flex gap-3 mt-2.5 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1"><BarChart3 className="w-3 h-3" />{demo.rows} rows</span>
                <span className="flex items-center gap-1"><FileSpreadsheet className="w-3 h-3" />{demo.cols} cols</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
