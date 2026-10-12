<script setup lang="ts">
// The pictures waiting above the field (docs/design/bug-reports.md), in the stack a goal let go over the field waits in
// (MovingStack.vue hosts both): 56 px tall, 8 px corners, 8 px apart, from the field's left end. The room they have is the
// field's width as it will be, which the field sets at once (--moving-field-width, --moving-tags-shift), so what overlaps is
// decided by CSS from those and the stack's own width, and the field's widening moves nothing under them: past a few they
// lie over each other, each less than the one before, and any number still fits.
//
// The one under the pointer lifts out of the others, bigger, as a picture on a table is held up to look at. What the pointer is
// on is the picture's place in the row, not the lifted picture, which lies over its neighbours and lets the pointer through:
// moving along the row lifts one after the other, none in the way of the next. A press picks it (Backspace picks the last):
// it stays lifted, with a small cross on its corner to take it off. A press leaves the keys where they are, in the field:
// the focus is what keeps the tags standing at the stack's left end, and the stack must not slide under the hand.
import AppIcon from './AppIcon.vue'
import { PICTURE_HEIGHT, pictures, removePicture, stackWidth, tapPicture, tileWidth } from '../lib/reportPictures'
import './fieldPictures.css'
</script>

<template>
  <div
    class="field-pictures"
    :class="{ 'is-sending': pictures.sending }"
    :style="{ '--stack': `${stackWidth(pictures.list)}px`, '--n': pictures.list.length, '--h': `${PICTURE_HEIGHT}px` }"
    data-role="field-pictures"
  >
    <div
      v-for="(picture, index) in pictures.list"
      :key="picture.id"
      class="field-pictures__item"
      :class="{ 'is-picked': pictures.picked === picture.id }"
      :style="{ '--w': `${tileWidth(picture)}px` }"
      data-role="field-picture"
    >
      <button
        type="button"
        class="field-pictures__hit"
        :aria-label="`Picture ${index + 1} of ${pictures.list.length}, ${picture.name}`"
        :aria-pressed="pictures.picked === picture.id"
        @mousedown.prevent
        @click.stop="tapPicture(picture.id)"
      ></button>
      <span class="field-pictures__pic" aria-hidden="true"><img :src="picture.url" alt="" draggable="false" decoding="async"></span>
      <button
        type="button"
        class="field-pictures__remove"
        :aria-label="`Take picture ${index + 1} off`"
        :tabindex="pictures.picked === picture.id ? 0 : -1"
        data-role="field-picture-remove"
        @mousedown.prevent
        @click.stop="removePicture(picture.id)"
      ><AppIcon name="x" :size="12" :stroke="2.8" /></button>
    </div>
  </div>
</template>
