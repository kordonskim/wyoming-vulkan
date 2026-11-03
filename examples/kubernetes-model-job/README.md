# Download once; start from persistent files

The existing Deployment installs packages, clones Git and checksums models on every new pod. This example moves
that work into a versioned Kubernetes Job. The application keeps using your existing image, configuration, HA Secret,
GPU settings and data PVC.

```text
Model Job (run when adding/changing models)
  -> install tools, fetch pinned catalog, download/verify files
  -> write models to the existing PVC -> finish

Application pod (every start)
  -> quick read-only file check -> load models from that PVC -> serve Wyoming
```

## Files to add to your Flux repository

1. Copy `models-job.yaml` into a models directory. Replace `claimName` with your existing data PVC name and use
   the same namespace as the Deployment. Both workloads select node `media`, matching your existing Deployment.
2. Include the Job in that directory's Kustomize `resources` list. Let it complete before removing the current
   downloading init container. Existing model files passing SHA-256 checks are reused; missing/corrupt files are downloaded.
3. Copy `deployment.patch.yaml` beside your existing application Kustomization, adjust its Deployment name if needed,
   and add it to `patches`:

   ```yaml
   patches:
     - path: deployment.patch.yaml
   ```

   It removes the init container named `fetch-models` and adds a read-only presence check. It keeps the existing
   Deployment's volumes and application container settings. Keep only the files for models you actually configure
   in the check list; the example checks all four models from your current download command.

The presence check reads file metadata, rather than hashing gigabytes on each pod start. SHA-256 verification
happens in the download Job. Your ConfigMap and HA credentials do not belong in the download Job.

## Flux ordering

For automatic ordering, put the Job in a separate Flux Kustomization named `wyoming-models` and set:

```yaml
spec:
  wait: true
  timeout: 120m
```

On the Flux Kustomization for the application, add:

```yaml
spec:
  dependsOn:
    - name: wyoming-models
```

These are fragments to merge into your existing Flux objects, not standalone manifests. The PVC must already
exist or be provided by an earlier storage Kustomization. If using ReadWriteOncePod storage, run the Job with the
application stopped because that access mode permits only one pod. Ordinary ReadWriteOnce storage can be shared
by pods on the same node, subject to your storage driver.

## When you add another model

Update the Job's model arguments, pin a newer catalog commit if needed, and rename the Job to `wyoming-models-v2`.
Kubernetes Jobs have immutable pod templates; a new name creates the new run. Keep the completed Job in Git and
omit `ttlSecondsAfterFinished`, so Flux does not continually recreate a deleted Job. Remove the old completed Job
manifest when replacing it; pruning it does not remove the separately managed PVC.

After the new Job succeeds, update the application config and file-check list, then roll out the application.
No new application image is required just to change model files. Ordinary application rollouts then require no
package-repository, GitHub or model-server access for model preparation. Container images must still be available
on the node or pullable from the registry.

This is a deployment example for review; it has not been applied to your cluster.
