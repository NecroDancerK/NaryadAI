export type WorkOrderStatus = 'issued' | 'accepted' | 'queued' | 'rejected' | 'in_progress' | 'paused' | 'completed' | 'ai_review' | 'rework' | 'closed'
export interface WorkOrder { id:number; number:string; description:string; work_type:'planned'|'unplanned'; site_id:number; equipment_id:number; assignee_id:number; master_id:number; priority:'emergency'|'high'|'normal'|'planned'; status:WorkOrderStatus; due_at:string; created_at:string }
export interface Directories { users:Array<{id:number;full_name:string;role:string;specialty:string|null}>; sites:Array<{id:number;name:string}>; equipment:Array<{id:number;name:string;site_id:number;inventory_number:string}>; fault_codes:Array<{id:number;code:string;name:string}>; materials:Array<{id:number;name:string;unit:string}> }
export interface AiInspection { id:number; work_order_id:number; verdict:'accepted'|'accepted_with_comments'|'rework'; score:number; confidence:number; checks:Array<{code:string;label:string;passed:boolean;severity:string;detail:string}>; explanation:string; analysis_source:string; model_name:string|null; llm_error:string|null; created_at:string }
export interface Notification { id:number; work_order_id:number; recipient_id:number; kind:string; title:string; message:string; is_read:boolean; created_at:string }
export interface ShiftReport { issued:number; completed:number; closed:number; active:number; overdue:number; rejected:number; average_response_minutes:number|null; by_status:Record<string,number>; by_priority:Record<string,number> }
export interface WorkerRating { worker_id:number; full_name:string; specialty:string|null; assigned:number; completed:number; score:number; components:{quality:number;timeliness:number;reliability:number;productivity:number;discipline:number}; facts:{average_quality:number;on_time:number;reworks:number;rejections:number;complexity_points:number} }
export interface HistoryAnalytics { period_days:number; orders_analyzed:number; top_equipment:Array<{equipment_id:number;name:string;unplanned_failures:number;downtime_hours:number}>; repeated_faults:Array<{equipment:string;fault_code:string;fault:string;count:number;recommendation:string}>; material_anomalies:Array<{work_order:string;material:string;quantity:number;average:number;deviation_factor:number}>; patterns:Array<{kind:string;severity:string;title:string;evidence:string;recommendation:string}> }
const apiUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export const wsUrl = `${import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'}/api/ws`
async function request<T>(path:string, options?:RequestInit):Promise<T> { const response=await fetch(`${apiUrl}${path}`,{...options,headers:{'Content-Type':'application/json',...options?.headers}}); if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(body?.detail??`Ошибка API: ${response.status}`)} return response.json() as Promise<T> }
export const api={
  health:()=>request<{status:string}>('/api/health'),
  directories:()=>request<Directories>('/api/directories'),
  workOrders:()=>request<WorkOrder[]>('/api/work-orders'),
  createWorkOrder:(payload:Record<string,unknown>)=>request<WorkOrder>('/api/work-orders',{method:'POST',body:JSON.stringify(payload)}),
  transition:(id:number,status:WorkOrderStatus,comment?:string,actorId=2)=>request<WorkOrder>(`/api/work-orders/${id}/transitions`,{method:'POST',body:JSON.stringify({actor_id:actorId,status,comment})}),
  complete:async(id:number,data:FormData):Promise<WorkOrder>=>{const response=await fetch(`${apiUrl}/api/work-orders/${id}/complete`,{method:'POST',body:data});if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(body?.detail??`Ошибка API: ${response.status}`)}return response.json()},
  aiReviews:()=>request<AiInspection[]>('/api/ai-reviews'),
  aiStatus:()=>request<{enabled:boolean;available:boolean;model:string;detail:string}>('/api/ai/status'),
  runAiReview:(id:number)=>request<AiInspection>(`/api/work-orders/${id}/ai-review`,{method:'POST'}),
  notifications:(recipientId:number)=>request<Notification[]>(`/api/notifications?recipient_id=${recipientId}`),
  readNotification:(id:number)=>request<Notification>(`/api/notifications/${id}/read`,{method:'POST'}),
  shiftReport:()=>request<ShiftReport>('/api/reports/shift'),
  ratings:()=>request<{weights:Record<string,number>;workers:WorkerRating[]}>('/api/reports/ratings'),
  historyAnalytics:()=>request<HistoryAnalytics>('/api/analytics/history'),
}
