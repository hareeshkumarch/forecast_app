import { useQuery, useMutation } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useToast } from "@/hooks/use-toast";
import { EmptyState } from "@/components/empty-state";
import { PageSkeleton } from "@/components/page-skeleton";
import type { Job } from "@shared/schema";
import {
  Clock, CheckCircle2, AlertCircle, Loader2, Trash2, Eye, BarChart3,
} from "lucide-react";


const IN_PROGRESS = new Set(["queued", "processing", "preprocessing", "training"]);

export default function HistoryPage() {
  const [, navigate] = useLocation();
  const { toast } = useToast();

  const { data: jobs, isLoading } = useQuery<Job[]>({
    queryKey: ["/api/jobs"],
    // Only poll while there are in-progress jobs — stops unnecessary calls when all complete
    refetchInterval: (query) => {
      const data = query.state.data as Job[] | undefined;
      if (!data) return 5000;
      return data.some((j) => IN_PROGRESS.has(j.status)) ? 5000 : false;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (jobId: string) => {
      await apiRequest("DELETE", `/api/jobs/${jobId}`);
    },
    onMutate: async (jobId) => {
      await queryClient.cancelQueries({ queryKey: ["/api/jobs"] });
      const previous = queryClient.getQueryData<Job[]>(["/api/jobs"]);
      queryClient.setQueryData<Job[]>(["/api/jobs"], (old: Job[] | undefined) =>
        (old || []).filter((j: Job) => j.id !== jobId)
      );
      return { previous };
    },
    onError: (_err, _jobId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["/api/jobs"], context.previous);
      }
      toast({ title: "Delete failed", description: "Could not remove job", variant: "destructive" });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/jobs"] });
    },
    onSuccess: () => {
      toast({ title: "Deleted", description: "Job removed from history" });
    },
  });


  const statusIcon = (status: string) => {
    switch (status) {
      case "completed": return <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />;
      case "failed": return <AlertCircle className="w-3.5 h-3.5 text-destructive" />;
      default:
        if (IN_PROGRESS.has(status)) return <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />;
        return <Clock className="w-3.5 h-3.5 text-muted-foreground" />;
    }
  };

  const statusBadge = (status: string) => {
    const variant = status === "completed" ? "default" : status === "failed" ? "destructive" : "outline";
    return <Badge variant={variant} className="text-[10px] px-1.5 py-0">{status}</Badge>;
  };

  return (
    <TooltipProvider delayDuration={300}>
      <div className="p-6 max-w-7xl mx-auto space-y-6 animate-fade-in">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Forecast History</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Manage your saved {(jobs?.length ?? 0) !== 1 ? "forecasts" : "forecast"} and monitor running jobs.
              <Badge variant="secondary" className="ml-2 px-1.5 font-mono text-[10px]">{jobs?.length ?? 0} total</Badge>
            </p>
          </div>
          {jobs && jobs.length > 0 && (
            <Button onClick={() => navigate("/")} className="gap-1.5 shadow-sm hover:shadow-md transition-all" data-testid="btn-new-forecast">
              <BarChart3 className="w-4 h-4" /> New Forecast
            </Button>
          )}
        </div>

        {isLoading ? (
          <PageSkeleton cards={0} chart={false} />
        ) : !jobs || jobs.length === 0 ? (
          <EmptyState
            icon={Clock}
            title="No forecasts yet"
            description="Create your first forecast to see it here"
            actionLabel="New Forecast"
            onAction={() => navigate("/")}
          />
        ) : (
          <Card>
            <CardContent className="pt-3 overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs font-medium">Job</TableHead>
                    <TableHead className="text-xs font-medium hidden md:table-cell">File</TableHead>
                    <TableHead className="text-xs font-medium">Progress</TableHead>
                    <TableHead className="text-xs font-medium">Status</TableHead>
                    <TableHead className="text-xs font-medium hidden lg:table-cell">Created</TableHead>
                    <TableHead className="text-xs font-medium text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((job) => {
                    const isInProgress = IN_PROGRESS.has(job.status);
                    const total = job.total_models || 0;
                    const done = job.completed_models || 0;
                    const progressPct = total > 0 ? Math.round((done / total) * 100) : 0;

                    return (
                      <TableRow key={job.id} className="cursor-pointer hover:bg-muted/30" onClick={() => {
                        if (job.status === "completed") navigate(`/results/${job.id}`);
                        else navigate(`/training/${job.id}`);
                      }}>
                        <TableCell>
                          <div className="flex flex-col gap-0.5 max-w-[120px] sm:max-w-[200px]">
                            <p className="text-sm font-medium truncate" title={job.name || job.id}>{job.name || job.id}</p>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <p className="text-[10px] font-mono text-muted-foreground truncate cursor-help w-full hover:text-foreground transition-colors">{job.id}</p>
                              </TooltipTrigger>
                              <TooltipContent side="right">
                                <p className="text-xs font-mono">{job.id}</p>
                              </TooltipContent>
                            </Tooltip>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm hidden md:table-cell max-w-[150px]">
                          <p className="truncate" title={job.original_filename || ""}>{job.original_filename || "—"}</p>
                        </TableCell>
                        <TableCell>
                          {job.status === "completed" ? (
                            <span className="text-xs text-muted-foreground tabular-nums inline-flex items-center gap-1.5 mt-1">
                              <CheckCircle2 className="w-3.5 h-3.5 text-green-500/70" /> {total} models
                            </span>
                          ) : isInProgress && total > 0 ? (
                            <div className="space-y-1.5 min-w-[100px] max-w-[150px]">
                              <div className="flex justify-between items-center text-[10px] font-medium text-muted-foreground">
                                <span>{done} / {total}</span>
                                <span className="text-primary">{progressPct}%</span>
                              </div>
                              <Progress value={progressPct} className="h-1.5 bg-secondary/60" />
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            {statusIcon(job.status)}
                            {statusBadge(job.status)}
                          </div>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground hidden lg:table-cell">
                          {job.created_at ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(job.created_at)) : "—"}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0 hover:bg-muted"
                                  onClick={() => {
                                    if (job.status === "completed") navigate(`/results/${job.id}`);
                                    else navigate(`/training/${job.id}`);
                                  }}
                                  data-testid={`btn-view-${job.id}`}
                                >
                                  <Eye className="w-4 h-4 text-muted-foreground hover:text-foreground transition-colors" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>View Details</TooltipContent>
                            </Tooltip>

                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0 hover:bg-destructive/10 hover:text-destructive transition-colors group"
                                  data-testid={`btn-delete-${job.id}`}
                                >
                                  <Trash2 className="w-4 h-4 text-muted-foreground group-hover:text-destructive transition-colors" />
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent onClick={(e) => e.stopPropagation()}>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>Delete forecast job?</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    Are you sure you want to delete this forecast job? This action cannot be undone and you will lose all results and data.
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                                  <AlertDialogAction
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      deleteMutation.mutate(job.id);
                                    }}
                                    className="bg-destructive hover:bg-destructive/90 text-destructive-foreground"
                                  >
                                    Delete Job
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </div>
    </TooltipProvider>
  );
}
