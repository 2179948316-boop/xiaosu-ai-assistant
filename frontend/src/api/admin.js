// 管理后台 API（仅管理员可访问）
import api from './index'

// 对话日志列表（分页 + 用户/时间筛选）
export const getAdminLogs = (params) => api.get('/admin/logs', { params })

// 单对话完整消息（tool_calls / token_count / sources）
export const getAdminLogDetail = (convId) => api.get(`/admin/logs/${convId}`)

// 系统设置（当前模型 / 白名单 / 飞书 bot 状态）
export const getAdminSettings = () => api.get('/admin/settings')

// 切换 LLM 模型
export const updateAdminSettings = (data) => api.post('/admin/settings', data)
