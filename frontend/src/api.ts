export type WorkOrderStatus = 'issued' | 'accepted' | 'queued' | 'rejected' | 'in_progress' | 'paused' | 'completed' | 'ai_review' | 'rework' | 'closed'
export interface WorkOrder { id:number; number:string; description:string; work_type:'planned'|'unplanned'; site_id:number; equipment_id:number; assignee_id:number; master_id:number; priority:'emergency'|'high'|'normal'|'planned'; status:WorkOrderStatus; due_at:string; created_at:string }
export interface Directories { users:Array<{id:number;full_name:string;role:string;specialty:string|null}>; sites:Array<{id:number;name:string}>; equipment:Array<{id:number;name:string;site_id:number;inventory_number:string}> }
const apiUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export const wsUrl = `${import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'}/api/ws`
async function request<T>(path:string, options?:RequestInit):Promise<T> { const response=await fetch(`${apiUrl}${path}`,{...options,headers:{'Content-Type':'application/json',...options?.headers}}); if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(body?.detail??`Ошибка API: ${response.status}`)} return response.json() as Promise<T> }
export const api={
  health:()=>request<{status:string}>('/api/health'),
  directories:()=>request<Directories>('/api/directories'),
  workOrders:()=>request<WorkOrder[]>('/api/work-orders'),
  createWorkOrder:(payload:Record<string,unknown>)=>request<WorkOrder>('/api/work-orders',{method:'POST',body:JSON.stringify(payload)}),
  transition:(id:number,status:WorkOrderStatus,comment?:string)=>request<WorkOrder>(`/api/work-orders/${id}/transitions`,{method:'POST',body:JSON.stringify({actor_id:2,status,comment})}),
}
