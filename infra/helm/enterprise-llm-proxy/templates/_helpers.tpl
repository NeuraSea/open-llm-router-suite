{{- define "enterprise-llm-proxy.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "enterprise-llm-proxy.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- include "enterprise-llm-proxy.name" . | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "enterprise-llm-proxy.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{- define "enterprise-llm-proxy.labels" -}}
helm.sh/chart: {{ include "enterprise-llm-proxy.chart" . }}
app.kubernetes.io/name: {{ include "enterprise-llm-proxy.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "enterprise-llm-proxy.selectorLabels" -}}
app.kubernetes.io/name: {{ include "enterprise-llm-proxy.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "enterprise-llm-proxy.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "enterprise-llm-proxy.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
