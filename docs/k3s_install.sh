#!/bin/bash
# K3s Installation Script for Agent Hub (Phase 1)
# Recommended instance: AWS EC2 t4g.large or larger

echo "Starting K3s installation..."

# Install K3s using the official script
curl -sfL https://get.k3s.io | sh -

# Ensure the KUBECONFIG is set up for the current user
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
export KUBECONFIG=~/.kube/config

# Verify installation
echo "Checking K3s node status..."
kubectl get nodes

echo "K3s installation complete. Traefik Ingress controller is installed by default."