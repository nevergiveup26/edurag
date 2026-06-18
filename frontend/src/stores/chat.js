import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref([])
  const currentConversationId = ref('')
  const messages = ref([])

  function addMessage(role, content) {
    messages.value.push({ role, content, time: new Date().toISOString() })
  }

  function clearMessages() {
    messages.value = []
    currentConversationId.value = ''
  }

  return { conversations, currentConversationId, messages, addMessage, clearMessages }
})