import api from './index'

// 知识库
export const getKnowledgeBases = () => api.get('/knowledge-bases')
export const createKnowledgeBase = (data) => api.post('/knowledge-bases', data)
export const deleteKnowledgeBase = (id) => api.delete(`/knowledge-bases/${id}`)

// 文档
export const uploadDocument = (kbId, file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/documents/upload?kb_id=${kbId}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
    onUploadProgress: onProgress,
  })
}
export const getDocuments = (kbId) => api.get(`/documents/${kbId}`)
export const deleteDocument = (docId) => api.delete(`/documents/${docId}`)
