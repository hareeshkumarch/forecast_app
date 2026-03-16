import { useEffect } from "react";
import { Switch, Route, Router, useLocation } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/not-found";
import HomePage from "@/pages/home";
import TrainingPage from "@/pages/training";
import ResultsPage from "@/pages/results";
import HistoryPage from "@/pages/history";
import DatabasePage from "@/pages/database";
import AppLayout from "@/components/app-layout";

const BASE_TITLE = "ForecastHub";

function usePageTitle() {
  const [location] = useLocation();
  useEffect(() => {
    const path = location.startsWith("/") ? location.slice(1) : location;
    if (path.startsWith("training/")) {
      document.title = `Training – ${BASE_TITLE}`;
    } else if (path.startsWith("results/")) {
      document.title = `Results – ${BASE_TITLE}`;
    } else if (path === "history") {
      document.title = `History – ${BASE_TITLE}`;
    } else if (path === "database") {
      document.title = `Database – ${BASE_TITLE}`;
    } else if (path === "" || path === "/") {
      document.title = BASE_TITLE;
    } else {
      document.title = BASE_TITLE;
    }
  }, [location]);
}

function AppRouter() {
  usePageTitle();
  return (
    <AppLayout>
      <Switch>
        <Route path="/" component={HomePage} />
        <Route path="/training/:jobId" component={TrainingPage} />
        <Route path="/results/:jobId" component={ResultsPage} />
        <Route path="/history" component={HistoryPage} />
        <Route path="/database" component={DatabasePage} />
        <Route component={NotFound} />
      </Switch>
    </AppLayout>
  );
}

import { ErrorBoundary } from "@/components/error-boundary";

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <Toaster />
          <Router hook={useHashLocation}>
            <AppRouter />
          </Router>
        </TooltipProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
