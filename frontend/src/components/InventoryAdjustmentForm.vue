<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { products } from '../api'

const props = defineProps({ productId: { type: [String, Number], required: true }, variant: { type: Object, required: true } })
const emit = defineEmits(['saved', 'busy', 'dirty', 'cancel'])
const amount = ref('')
const reason = ref('')
const pending = ref(false)
const errors = ref({})
const message = ref('')
const success = ref('')
const amountInput = ref(null)
const dialog = ref(null)
let previousOverflow
const delta = computed(() => /^[+-]?\d+$/.test(amount.value.trim()) ? Number(amount.value) : NaN)
const validDelta = computed(() => Number.isSafeInteger(delta.value) && delta.value !== 0 && Math.abs(delta.value) <= 2147483647)
const proposed = computed(() => validDelta.value ? props.variant.inventory.quantity + delta.value : null)
const previewError = computed(() => {
  if (proposed.value === null) return ''
  const { quantity, reserved } = props.variant.inventory
  if (proposed.value < reserved) return `Cannot go below ${reserved} reserved units. You can remove at most ${quantity - reserved} units.`
  if (proposed.value > 2147483647) return 'Cannot exceed the maximum quantity of 2,147,483,647 units.'
  return ''
})
const dirty = computed(() => amount.value !== '' || reason.value !== '')
watch(dirty, value => emit('dirty', value), { flush: 'sync' })
onMounted(async () => {
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  dialog.value.showModal()
  await nextTick()
  amountInput.value?.focus()
})
onBeforeUnmount(() => {
  dialog.value?.close()
  document.body.style.overflow = previousOverflow
})

function containFocus(event) {
  const controls = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled)')].filter(control => control.getClientRects().length)
  const first = controls[0]
  const last = controls.at(-1)
  if (!first) {
    event.preventDefault()
    dialog.value.focus()
  } else if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || !controls.includes(document.activeElement))) {
    event.preventDefault()
    first.focus()
  }
}

function backdropClick(event) {
  if (event.target !== dialog.value) return
  const bounds = dialog.value.getBoundingClientRect()
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) cancel()
}

function fieldError(field) {
  const value = errors.value[field]
  return Array.isArray(value) ? value.join(' ') : typeof value === 'string' ? value : ''
}

function cancel() {
  if (pending.value || (dirty.value && !window.confirm('Discard this unfinished inventory adjustment?'))) return
  emit('cancel')
}

async function submit() {
  if (pending.value) return
  errors.value = {}
  message.value = ''
  success.value = ''
  if (!validDelta.value) errors.value.delta = 'Enter a nonzero whole-number adjustment within ±2,147,483,647.'
  if (!reason.value.trim() || reason.value.trim().length > 500) errors.value.reason = 'Enter a reason of 1–500 characters.'
  if (Object.keys(errors.value).length) return
  pending.value = true
  emit('busy', true)
  try {
    const result = await products.adjustInventory(props.productId, props.variant.id, { delta: delta.value, reason: reason.value.trim() })
    emit('saved', result)
    success.value = `Stock adjusted: ${result.adjustment.quantity_before} → ${result.adjustment.quantity_after}. Adjustment #${result.adjustment.id}.`
    amount.value = ''
    reason.value = ''
  } catch (failure) {
    if (failure.status === 400) errors.value = failure.fields || {}
    message.value = failure.status === 409
      ? `${failure.message} Stock may have changed since this page loaded. Check the current stock before trying again.`
      : !failure.status || failure.status >= 500
        ? 'The outcome could not be confirmed. Check activity and current stock before submitting another adjustment; it may already have been saved.'
        : failure.message
  } finally {
    pending.value = false
    emit('busy', false)
  }
}
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="inventory-dialog" :aria-labelledby="'adjustment-title-' + variant.id" aria-modal="true" @cancel.prevent="cancel" @click="backdropClick" @keydown.tab="containFocus">
      <form class="inventory-adjustment" :aria-label="'Adjust stock for ' + variant.name" :aria-busy="pending" novalidate @submit.prevent="submit">
        <header class="inventory-dialog-header">
          <h2 :id="'adjustment-title-' + variant.id">Adjust stock: {{ variant.name }}</h2>
          <button class="inventory-dialog-close" type="button" aria-label="Dismiss stock dialog" :disabled="pending" @click="cancel"><span aria-hidden="true">×</span></button>
        </header>
        <p class="code">{{ variant.sku }}</p>
        <p>Quantity: {{ variant.inventory.quantity }} · Reserved: {{ variant.inventory.reserved }} · Available: {{ variant.inventory.quantity - variant.inventory.reserved }}</p>
        <fieldset class="editor-fields" :disabled="pending">
          <div class="form-grid">
            <label class="field" :for="'adjustment-delta-' + variant.id">Adjustment amount
              <input :id="'adjustment-delta-' + variant.id" ref="amountInput" aria-label="Adjustment amount" v-model="amount" type="text" inputmode="text" maxlength="12" required :aria-invalid="!!fieldError('delta')" :aria-describedby="'adjustment-delta-help-' + variant.id + (fieldError('delta') ? ' adjustment-delta-error-' + variant.id : '')" />
              <small :id="'adjustment-delta-help-' + variant.id">Use a positive number to add stock or a negative number to remove it, for example +3 or -3.</small>
              <span v-if="fieldError('delta')" :id="'adjustment-delta-error-' + variant.id" class="error-text">{{ fieldError('delta') }}</span>
            </label>
            <label class="field" :for="'adjustment-reason-' + variant.id">Reason
              <textarea :id="'adjustment-reason-' + variant.id" v-model="reason" aria-label="Reason" :aria-describedby="fieldError('reason') ? 'adjustment-reason-error-' + variant.id : undefined" rows="2" maxlength="500" required :aria-invalid="!!fieldError('reason')" />
              <span v-if="fieldError('reason')" :id="'adjustment-reason-error-' + variant.id" class="error-text">{{ fieldError('reason') }}</span>
            </label>
          </div>
        </fieldset>
        <p class="inventory-preview" :class="{ 'error-text': !!previewError }" aria-live="polite">
          Proposed quantity: {{ proposed === null ? '—' : proposed }}
          <span v-if="previewError"> — {{ previewError }}</span>
        </p>
        <p class="inventory-help">Preview only. Current stock is checked again when the adjustment is saved.</p>
        <p v-if="message || Object.keys(errors).length" class="error-text" role="alert">{{ message || 'Correct the highlighted fields.' }}</p>
        <p v-if="success" class="success-text" role="status">{{ success }}</p>
        <p v-if="pending" role="status">Saving inventory adjustment…</p>
        <div class="inventory-actions">
          <button class="button button-primary" type="submit" :disabled="pending">{{ pending ? 'Saving adjustment…' : 'Apply adjustment' }}</button>
          <button class="button" type="button" :disabled="pending" @click="cancel">Close adjustment</button>
        </div>
      </form>
    </dialog>
  </Teleport>
</template>
