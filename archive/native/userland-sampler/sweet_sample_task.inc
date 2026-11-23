void
sweet_sample_task(const char *name, int pid, task_t task)
{
	/* Capture registers while the thread list is stable. Stack reads may fault:
	 * never hold task->lock across vm_map_read_user(). No thread pointer is
	 * retained after the lock is released; the map has its own reference.
	 */
	enum { MAX_SAMPLE_THREADS = 128 };
	struct sweet_sample_regs { uint64_t pc, lr, sp, fp; };
	struct sweet_sample_regs *regs = kalloc_data(
	    sizeof(*regs) * MAX_SAMPLE_THREADS, Z_WAITOK | Z_ZERO);
	vm_map_t map = get_task_map_reference(task);
	uint64_t slide = 0, mh = 0;
	unsigned count = 0;
	bool truncated = false;
	thread_t thread;
	vm_shared_region_t sr = vm_shared_region_get(task);

	if (sr != NULL) {
		slide = sr->sr_slide;
		vm_shared_region_deallocate(sr);
	}
	if (regs == NULL || map == VM_MAP_NULL) {
		if (regs != NULL) kfree_data(regs, sizeof(*regs) * MAX_SAMPLE_THREADS);
		if (map != VM_MAP_NULL) vm_map_deallocate(map);
		printf("SMP %s[%d] unavailable\n", name, pid);
		return;
	}
	task_lock(task);
	mh = task->mach_header_vm_address;
	queue_iterate(&task->threads, thread, thread_t, task_threads) {
		arm_saved_state_t *ss = find_user_regs(thread);
		if (ss == NULL || !is_saved_state64(ss)) continue;
		if (count == MAX_SAMPLE_THREADS) { truncated = true; break; }
		regs[count++] = (struct sweet_sample_regs) {
			.pc = get_saved_state_pc(ss), .lr = get_saved_state_lr(ss),
			.sp = get_saved_state_sp(ss), .fp = get_saved_state_fp(ss),
		};
	}
	task_unlock(task);
	printf("SMP %s[%d] slide 0x%llx mh 0x%llx\n", name, pid, slide, mh);
	for (unsigned tn = 0; tn < count; tn++) {
		char line[400];
		uint64_t fp = regs[tn].fp;
		int n = snprintf(line, sizeof(line), "SMP %s t%u pc 0x%llx lr 0x%llx sp 0x%llx bt",
		    name, tn, regs[tn].pc, regs[tn].lr, regs[tn].sp);
		for (int i = 0; i < 16 && fp != 0 && (fp & 7) == 0 && n < (int)sizeof(line) - 20; i++) {
			uint64_t frame[2];
			if (vm_map_read_user(map, fp, frame, sizeof(frame)) != KERN_SUCCESS) break;
			n += snprintf(line + n, sizeof(line) - n, " 0x%llx", frame[1]);
			if (frame[0] <= fp) break;
			fp = frame[0];
		}
		printf("%s\n", line);
	}
	printf("SMP END %s[%d] threads=%u truncated=%u\n", name, pid, count, truncated);
	vm_map_deallocate(map);
	kfree_data(regs, sizeof(*regs) * MAX_SAMPLE_THREADS);
}
