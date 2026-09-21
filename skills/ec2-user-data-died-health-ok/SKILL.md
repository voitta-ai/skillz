---
name: ec2-user-data-died-health-ok
description: |
  Diagnose an EC2 instance that boots clean and serves nothing, where every
  AWS-visible health field reads ok because the instance really is healthy and
  it is cloud-init that died. Use when: (1) an instance is `running` with
  `SystemStatus: ok` and `InstanceStatus: ok`, SSH answers, but the ports your
  user_data was supposed to open are closed, (2) software the bootstrap
  installs is simply absent and nothing in the console suggests why, (3) you
  are running any `dnf`/`apt` operation inside user_data on a 512 MB instance
  (`t4g.nano`, `t3.nano`, `t2.nano`), (4) a bootstrap under `set -e` stopped
  partway and you cannot tell where, (5) you edited user_data in Terraform and
  the plan says "will be updated in-place, 0 to destroy" - that plan is a
  no-op. Two traps: instance status answers "is the VM alive", never "did
  cloud-init finish", so a green check is not evidence the bootstrap ran; and
  `user_data` is read only on first boot, so changing it in place changes an
  API field while the running machine stays exactly as broken.
author: Claude Code
version: 1.0.0
date: 2026-09-21
---

# The instance is fine. The bootstrap is dead.

## Problem

You launch an instance with a user_data bootstrap. Terraform reports success.
`describe-instance-status` returns `running`, `ok`, `ok`. SSH works. And the
service you installed is not there, with the ports shut.

Nothing errored anywhere you looked, because everything you looked at was
answering a different question. Instance status reports on the virtual
machine - is it scheduled, is the network attached, does the OS respond. It
has no opinion whatsoever about whether cloud-init ran your script to
completion. A bootstrap that died on line 8 of 60 produces exactly the same
three green fields as one that finished.

## Where the truth actually lives

In this order, because each needs less access than the last:

1. **`aws ec2 get-console-output --instance-id <id>`** - needs no SSH, no
   agent, and survives the instance being wedged. Kernel messages are here,
   which is where an OOM kill is recorded, and on AL2023 and Ubuntu the
   cloud-init script output lands here too.
2. **`/var/log/cloud-init-output.log`** - the full captured stdout/stderr of
   your script, with the shell's own error line.
3. **Your own log**, if the script has one. Useful, but it is written by the
   thing that died, so it stops before the interesting part. Never rely on it
   alone.

A kernel OOM in the console looks like this, and names both the victim and the
script line:

```
Out of memory: Killed process 2018 (dnf) total-vm:1175220kB, anon-rss:175624kB
/var/lib/cloud/instance/scripts/part-001: line 8:  2018 Killed   dnf -y update
Cloud-init received SIGTERM, exiting...
```

## Trap 1: package managers do not fit on a nano

`t4g.nano`, `t3.nano` and `t2.nano` all have 512 MB. A full `dnf -y update`
or a large `apt upgrade` peaks well past that resolving dependencies, and the
kernel kills it. The instance is untouched by this; only your script dies.

Three fixes, apply all three:

- **Swap first, before anything memory-hungry.** A 1 GB swapfile as the very
  first action of the bootstrap turns a kill into slowness. On a small box
  this is the difference between working and not.
- **Do not install what is already there.** Amazon Linux 2023 ships `tar`,
  `gzip` and `curl-minimal`. Assert with `command -v` and fail loudly naming
  the missing tool, rather than reflexively installing.
- **Make patching non-fatal.** `dnf -y --security update || echo WARN` is far
  smaller than a full update, and the `||` guarantees that patching can never
  prevent the service from coming up.

## Trap 2: `set -e` makes every optional command fatal

`set -euxo pipefail` is correct for a bootstrap, but it means one unnecessary
line - a cosmetic update, a `timedatectl`, a metrics agent - takes the whole
machine down with it. Audit a bootstrap for commands whose failure should not
be fatal and mark them `|| true` explicitly. The ones that must succeed stay
bare, and now that is a statement rather than an accident.

## Trap 3: editing user_data in Terraform plans as a no-op

The `aws` provider defaults `user_data_replace_on_change = false`. So after
fixing your bootstrap, the plan reads:

```
  # aws_instance.x will be updated in-place
Plan: 0 to add, 1 to change, 0 to destroy.
```

That is not a fix. cloud-init reads user_data **only on first boot**, so the
apply updates an API attribute and the running machine stays exactly as
broken - and the plan's zero destroy count makes it look like the safe
outcome. Set it in the resource, so the property holds for every future edit:

```hcl
user_data_replace_on_change = true
```

The honest plan then says `must be replaced`. If the instance carries an
Elastic IP as its own resource, the address and any DNS record pointing at it
survive the replacement; the EIP shows as an in-place modify.

## Procedure

1. Confirm the shape: instance `running` and both checks `ok`, but the
   expected port is closed. `nc -z <ip> <port>` is enough.
2. `get-console-output` and read the tail. Do not SSH first; the console needs
   no working service and shows kernel events SSH cannot.
3. Find the last line the script reached. Under `set -x` every command is
   echoed, so the final echoed command is the one that died.
4. Fix the cause, then check `user_data_replace_on_change` before believing
   any plan that says in-place.
5. After re-apply, verify by the service responding, not by instance status.
   Poll the actual health endpoint.

## Gotchas

- **`free -m` early in the bootstrap is cheap insight.** It lands in the
  console output and tells you your headroom before anything consumed it.
- **A green Terraform apply proves the API accepted the launch**, nothing
  about what the machine did afterwards. The two are separated by minutes.
- **Console output lags.** It can be a minute or two behind, and on some
  instance types is only refreshed periodically. An empty result early on is
  "not yet", not "nothing happened".
- **SSH working is not a signal.** `sshd` comes from the base image and runs
  whether or not your script did anything at all.

## Related

- `cloudwatch-alarm-cannot-fire-audit` - the same discipline for alarms: a
  metric that never reports is not a metric that is fine.
- `terraform-plan-unrelated-destroy-drift` - the other direction, where a plan
  proposes more than you meant rather than less.
