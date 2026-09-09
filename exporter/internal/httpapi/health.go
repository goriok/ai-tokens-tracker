package httpapi

import "net/http"

// HealthHandler is a trivial liveness check — 200 iff the process is up
// and answering HTTP. Not a readiness check: it doesn't verify the ingest
// loop is making progress (that's aitokens_ingest_last_id in /metrics).
func HealthHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})
}
