// The controls: one button per command, and a composer form (arguments + required reason).
// Built once; later renders only toggle "enabled", so typing is never interrupted.
import {
  COMMAND_SPECS,
  GROUP_LABELS,
  REASONS,
  specFor,
  validateCommandForm,
  type ArgField,
  type CommandGroup,
  type CommandName,
  type CommandPayload,
} from './commands';
import { byId, h, setText } from './dom';
import { humanize } from './format';

export const CONFIRM_WINDOW_MS = 4000;

export interface ComposerHooks {
  /** Send a validated command. Returns an error text, or null when it was sent. */
  readonly send: (payload: CommandPayload) => string | null;
}

export interface Composer {
  setEnabled(enabled: boolean): void;
  /** Reason/note as currently typed (the emergency stop reuses them if valid). */
  draftReason(): { reason: string; note: string };
}

const GROUP_ORDER: readonly CommandGroup[] = ['session', 'flow', 'speech', 'games', 'body'];

function fieldInput(field: ArgField): HTMLElement {
  const id = `arg-${field.key}`;
  switch (field.kind) {
    case 'toggle':
      return h('input', { attrs: { id, name: field.key, type: 'checkbox', value: 'true' } });
    case 'select': {
      const select = h('select', { attrs: { id, name: field.key, required: '' } }, [
        h('option', { text: `Choose…`, attrs: { value: '' } }),
        ...field.options.map((option) =>
          h('option', { text: humanize(option), attrs: { value: option } }),
        ),
      ]);
      return select;
    }
    case 'number':
      return h('input', {
        attrs: {
          id,
          name: field.key,
          type: 'number',
          inputmode: 'numeric',
          min: String(field.min),
          max: String(field.max),
          step: '1',
          placeholder: '60',
        },
      });
    case 'text': {
      const listId = field.suggestions.length ? `${id}-list` : '';
      const attrs: Record<string, string> = {
        id,
        name: field.key,
        maxlength: String(field.maxLength),
        autocomplete: 'off',
      };
      if (listId) attrs.list = listId;
      const input = field.multiline
        ? h('textarea', { attrs: { ...attrs, rows: '3' } })
        : h('input', { attrs: { ...attrs, type: 'text' } });
      const list = listId
        ? h(
            'datalist',
            { attrs: { id: listId } },
            field.suggestions.map((s) => h('option', { attrs: { value: s } })),
          )
        : null;
      return h('div', { className: 'field-stack' }, [input, list]);
    }
  }
}

export function createComposer(hooks: ComposerHooks): Composer {
  const groups = byId('command-groups');
  const form = byId<HTMLFormElement>('composer');
  const title = byId('composer-title');
  const hint = byId('composer-hint');
  const fields = byId('composer-fields');
  const reason = byId<HTMLSelectElement>('reason');
  const note = byId<HTMLInputElement>('note');
  const keepReason = byId<HTMLInputElement>('keep-reason');
  const error = byId('form-error');
  const sendButton = byId<HTMLButtonElement>('send');
  const buttons = new Map<CommandName, HTMLButtonElement>();

  let selected: CommandName = 'next_phase';
  let enabled = false;
  let confirmUntil = 0;
  let confirmTimer: ReturnType<typeof setTimeout> | null = null;

  reason.replaceChildren(
    h('option', { text: 'Choose a reason…', attrs: { value: '' } }),
    ...REASONS.map((r) => h('option', { text: r.label, attrs: { value: r.value } })),
  );

  for (const group of GROUP_ORDER) {
    const specs = COMMAND_SPECS.filter(
      (spec) => spec.group === group && spec.name !== 'emergency_stop',
    );
    const row = h('div', { className: 'command-row' });
    for (const spec of specs) {
      const button = h('button', {
        className: 'command-button',
        text: spec.label,
        attrs: {
          type: 'button',
          'data-command': spec.name,
          'data-confirm': String(spec.confirm),
          'aria-pressed': 'false',
        },
      });
      button.addEventListener('click', () => select(spec.name));
      buttons.set(spec.name, button);
      row.append(button);
    }
    groups.append(
      h('fieldset', { className: 'command-group' }, [
        h('legend', { text: GROUP_LABELS[group] }),
        row,
      ]),
    );
  }

  function disarm(): void {
    confirmUntil = 0;
    if (confirmTimer) clearTimeout(confirmTimer);
    confirmTimer = null;
    form.dataset.confirming = 'false';
    updateSendLabel();
  }

  function updateSendLabel(): void {
    const spec = specFor(selected);
    const label = !enabled
      ? 'Not connected'
      : confirmUntil > Date.now()
        ? `Tap again to confirm: ${spec.label.replace('…', '')}`
        : `Send: ${spec.label.replace('…', '')}`;
    setText(sendButton, label);
    sendButton.disabled = !enabled;
  }

  function select(name: CommandName): void {
    selected = name;
    disarm();
    const spec = specFor(name);
    for (const [command, button] of buttons)
      button.setAttribute('aria-pressed', String(command === name));
    setText(title, spec.label.replace('…', ''));
    setText(hint, spec.hint);
    fields.replaceChildren(
      ...spec.fields.map((field) =>
        h(
          'label',
          {
            className: field.kind === 'toggle' ? 'field field-toggle' : 'field',
            attrs: { for: `arg-${field.key}` },
          },
          [
            h('span', { className: 'field-label', text: field.label }),
            fieldInput(field),
            h('span', { className: 'field-error', attrs: { 'data-for': field.key } }),
          ],
        ),
      ),
    );
    setText(error, '');
    form.dataset.command = name;
    updateSendLabel();
  }

  function showErrors(errors: Readonly<Record<string, string>>): void {
    for (const slot of form.querySelectorAll<HTMLElement>('.field-error')) {
      setText(slot, errors[slot.dataset.for ?? ''] ?? '');
    }
    setText(error, [errors.reason, errors.note].filter(Boolean).join(' · '));
    form.dataset.invalidReason = String(Boolean(errors.reason));
    form.dataset.invalidNote = String(Boolean(errors.note));
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!enabled) return;
    const values: Record<string, string> = {};
    for (const field of specFor(selected).fields) {
      const input = form.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
        `#arg-${field.key}`,
      );
      const isToggle = input instanceof HTMLInputElement && input.type === 'checkbox';
      values[field.key] = isToggle ? (input.checked ? 'true' : '') : (input?.value ?? '');
    }
    const result = validateCommandForm({
      command: selected,
      values,
      reason: reason.value,
      note: note.value,
    });
    if (!result.ok) {
      showErrors(result.errors);
      return;
    }
    showErrors({});
    if (specFor(selected).confirm && confirmUntil <= Date.now()) {
      confirmUntil = Date.now() + CONFIRM_WINDOW_MS;
      form.dataset.confirming = 'true';
      confirmTimer = setTimeout(disarm, CONFIRM_WINDOW_MS);
      updateSendLabel();
      return;
    }
    disarm();
    const failure = hooks.send(result.payload);
    if (failure) {
      setText(error, failure);
      return;
    }
    note.value = '';
    if (!keepReason.checked) reason.value = '';
    const text = form.querySelector<HTMLTextAreaElement>('#arg-text');
    if (text) text.value = '';
  });

  select(selected);

  return {
    setEnabled(next: boolean): void {
      if (next === enabled) return;
      enabled = next;
      if (!enabled) disarm();
      updateSendLabel();
    },
    draftReason: () => ({ reason: reason.value, note: note.value }),
  };
}
