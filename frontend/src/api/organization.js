import api from './index'

// 组织管理
export const getOrganizations = () => api.get('/organizations')
export const createOrganization = (data) => api.post('/organizations', data)
export const deleteOrganization = (orgId) => api.delete(`/organizations/${orgId}`)

// 成员管理
export const getOrgMembers = (orgId) => api.get(`/organizations/${orgId}/members`)
export const addOrgMember = (orgId, data) => api.post(`/organizations/${orgId}/members`, data)
export const removeOrgMember = (orgId, userId) => api.delete(`/organizations/${orgId}/members/${userId}`)
