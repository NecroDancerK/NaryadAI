import type { WorkOrder, WorkOrderStatus } from '../api'
export function initialMobileLane(lanes: Array<{ key: string; orders: unknown[] }>, selected: string | null): string {
  if (selected !== null) return selected
  if (lanes.some(lane => lane.key === 'overdue' && lane.orders.length > 0)) return 'overdue'
  return lanes.find(lane => lane.orders.length > 0)?.key ?? 'issued'
}
export const statusMeta:Record<WorkOrderStatus,{label:string;color:string}>={ issued:{label:'Выдан',color:'blue-grey'}, accepted:{label:'Принят',color:'blue'}, queued:{label:'В очереди',color:'indigo'}, rejected:{label:'Отклонён',color:'negative'}, in_progress:{label:'В работе',color:'amber-9'}, paused:{label:'Приостановлен',color:'orange'}, completed:{label:'Исполнен',color:'teal'}, ai_review:{label:'Проверка ИИ',color:'purple'}, rework:{label:'На доработке',color:'deep-orange'}, closed:{label:'Закрыт',color:'positive'} }
export function name(items:Array<{id:number;name?:string;full_name?:string}>|undefined,id:number){const item=items?.find(x=>x.id===id);return item?.name??item?.full_name??`#${id}`}
export function isOverdue(order:WorkOrder){return order.status!=='closed'&&new Date(order.due_at)<new Date()}
export function actions(order: WorkOrder): Array<{ label: string; status: WorkOrderStatus; color: string; icon: string }> {
  if (order.status === 'issued') return [{ label:'Принять',status:'accepted',color:'primary',icon:'check' },{ label:'В очередь',status:'queued',color:'indigo',icon:'playlist_add' },{ label:'Отклонить',status:'rejected',color:'negative',icon:'block' }]
  if (order.status === 'queued') return [{ label:'Принять',status:'accepted',color:'primary',icon:'check' }]
  if (order.status === 'accepted') return [{ label:'Начать',status:'in_progress',color:'positive',icon:'play_arrow' }]
  if (order.status === 'in_progress') return [{ label:'Приостановить',status:'paused',color:'warning',icon:'pause' },{ label:'Исполнено',status:'completed',color:'positive',icon:'task_alt' }]
  if (order.status === 'paused') return [{ label:'Продолжить',status:'in_progress',color:'primary',icon:'play_arrow' }]
  if (order.status === 'rework') return [{ label:'В работу',status:'in_progress',color:'deep-orange',icon:'build' }]
  return []
}
