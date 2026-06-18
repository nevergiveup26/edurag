import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'

describe('useChatStore', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useChatStore()
  })

  it('初始状态为空', () => {
    expect(store.messages).toEqual([])
    expect(store.currentConversationId).toBe('')
    expect(store.conversations).toEqual([])
  })

  it('addMessage 添加消息并附带时间戳', () => {
    store.addMessage('user', '你好')
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[0].content).toBe('你好')
    expect(store.messages[0].time).toBeTruthy()
  })

  it('addMessage 追加多条消息', () => {
    store.addMessage('user', '问题1')
    store.addMessage('assistant', '回答1')
    store.addMessage('user', '问题2')
    expect(store.messages).toHaveLength(3)
    expect(store.messages.map(m => m.role)).toEqual(['user', 'assistant', 'user'])
  })

  it('clearMessages 清空消息和当前会话 ID', () => {
    store.currentConversationId = 'conv_123'
    store.addMessage('user', 'hello')
    store.clearMessages()
    expect(store.messages).toEqual([])
    expect(store.currentConversationId).toBe('')
  })
})
