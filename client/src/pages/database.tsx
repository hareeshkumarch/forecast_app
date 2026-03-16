import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { PageSkeleton } from "@/components/page-skeleton";
import { EmptyState } from "@/components/empty-state";
import type { Job } from "@shared/schema";
import { Database, FileText, BarChart3, Clock, AlertCircle } from "lucide-react";

export default function DatabaseViewer() {
    const { data: jobs, isLoading: loadingJobs } = useQuery<Job[]>({
        queryKey: ["/api/jobs"],
    });

    const stats = {
        total: jobs?.length ?? 0,
        completed: jobs?.filter((j) => j.status === "completed").length ?? 0,
        failed: jobs?.filter((j) => j.status === "failed").length ?? 0,
        totalModels: jobs?.reduce((acc, j) => acc + (j.total_models || 0), 0) ?? 0,
    };

    const containerVariants = {
        hidden: { opacity: 0 },
        show: { opacity: 1, transition: { staggerChildren: 0.1 } },
    };
    const itemVariants = {
        hidden: { opacity: 0, y: 15 },
        show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } },
    };

    if (loadingJobs) {
        return <PageSkeleton cards={4} chart={false} />;
    }

    return (
        <motion.div initial="hidden" animate="show" variants={containerVariants} className="p-6 max-w-7xl mx-auto space-y-6">
            <motion.div variants={itemVariants} className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold flex items-center gap-2">
                        <Database className="w-6 h-6 text-primary" aria-hidden />
                        Database Explorer
                    </h1>
                    <p className="text-sm text-muted-foreground">Detailed view of all forecast jobs and model executions</p>
                </div>
            </motion.div>

            <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {[
                    { label: "Total Jobs", value: stats.total, icon: FileText },
                    { label: "Completed", value: stats.completed, icon: Clock, color: "text-green-500" },
                    { label: "Failed", value: stats.failed, icon: AlertCircle, color: "text-destructive" },
                    { label: "Models Trained", value: stats.totalModels, icon: BarChart3 },
                ].map((s) => (
                    <Card key={s.label} className="backdrop-blur-md bg-card/50 border-primary/10">
                        <CardContent className="py-4">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs text-muted-foreground">{s.label}</p>
                                    <p className={`text-2xl font-bold ${s.color || ""}`}>{s.value}</p>
                                </div>
                                <s.icon className={`w-8 h-8 opacity-20 ${s.color || ""}`} />
                            </div>
                        </CardContent>
                    </Card>
                ))}
            </motion.div>

            <motion.div variants={itemVariants}>
                <Card className="backdrop-blur-xl bg-card/30 border-primary/10 overflow-hidden hover:shadow-lg hover:shadow-primary/5 transition-all duration-300">
                    <CardHeader className="bg-muted/30 pb-4">
                        <CardTitle className="text-lg">Recent Jobs</CardTitle>
                        <CardDescription>Raw database entries for forecast tasks</CardDescription>
                    </CardHeader>
                    <CardContent className="p-0">
                        {(!jobs || jobs.length === 0) ? (
                            <div className="py-10">
                                <EmptyState
                                    icon={Database}
                                    title="No jobs yet"
                                    description="Forecast jobs will appear here once created."
                                />
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <Table>
                                    <TableHeader>
                                        <TableRow className="hover:bg-transparent">
                                            <TableHead className="w-[100px]">ID</TableHead>
                                            <TableHead>Target</TableHead>
                                            <TableHead>Freq</TableHead>
                                            <TableHead>Horizon</TableHead>
                                            <TableHead>Models</TableHead>
                                            <TableHead>Status</TableHead>
                                            <TableHead className="text-right">Created</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {jobs.map((job) => (
                                            <motion.tr
                                                key={job.id}
                                                initial="hidden"
                                                animate="show"
                                                variants={itemVariants}
                                                className="hover:bg-muted/30 transition-colors border-b last:border-0 cursor-pointer"
                                                whileHover={{ scale: 1.005 }}
                                                transition={{ type: "spring", stiffness: 400, damping: 25 }}
                                            >
                                                <TableCell className="font-mono text-[10px]">{job.id}</TableCell>
                                                <TableCell className="font-medium text-sm">{job.target_col}</TableCell>
                                                <TableCell><Badge variant="outline" className="text-[10px]">{job.frequency}</Badge></TableCell>
                                                <TableCell className="text-sm">{job.horizon}</TableCell>
                                                <TableCell className="text-sm">{job.completed_models}/{job.total_models}</TableCell>
                                                <TableCell>
                                                    <Badge
                                                        variant={job.status === "completed" ? "default" : job.status === "failed" ? "destructive" : "secondary"}
                                                        className="text-[10px]"
                                                    >
                                                        {job.status}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell className="text-right text-xs text-muted-foreground">
                                                    {job.created_at ? new Date(job.created_at).toLocaleDateString() : "—"}
                                                </TableCell>
                                            </motion.tr>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                        )}
                    </CardContent>
                </Card>
            </motion.div>
        </motion.div>
    );
}
