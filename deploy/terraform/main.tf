terraform {
  required_version = ">= 1.6"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 7.0"
    }
  }
}

provider "oci" {
  config_file_profile = var.oci_profile
  region              = var.region
}

data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu" {
  compartment_id           = var.tenancy_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "fetchall" {
  compartment_id = var.tenancy_ocid
  cidr_blocks    = ["10.42.0.0/16"]
  display_name   = "fetchall"
  dns_label      = "fetchall"
}

resource "oci_core_internet_gateway" "fetchall" {
  compartment_id = var.tenancy_ocid
  vcn_id         = oci_core_vcn.fetchall.id
  display_name   = "fetchall"
}

resource "oci_core_route_table" "fetchall" {
  compartment_id = var.tenancy_ocid
  vcn_id         = oci_core_vcn.fetchall.id
  display_name   = "fetchall"
  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.fetchall.id
  }
}

resource "oci_core_security_list" "fetchall" {
  compartment_id = var.tenancy_ocid
  vcn_id         = oci_core_vcn.fetchall.id
  display_name   = "fetchall"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  dynamic "ingress_security_rules" {
    for_each = toset(["22", "80", "443"])
    content {
      source   = "0.0.0.0/0"
      protocol = "6"
      tcp_options {
        min = tonumber(ingress_security_rules.value)
        max = tonumber(ingress_security_rules.value)
      }
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id    = var.tenancy_ocid
  vcn_id            = oci_core_vcn.fetchall.id
  cidr_block        = "10.42.1.0/24"
  display_name      = "fetchall-public"
  dns_label         = "public"
  route_table_id    = oci_core_route_table.fetchall.id
  security_list_ids = [oci_core_security_list.fetchall.id]
}

resource "oci_core_instance" "fetchall" {
  compartment_id      = var.tenancy_ocid
  availability_domain = data.oci_identity_availability_domains.all.availability_domains[0].name
  display_name        = "fetchall"
  shape               = "VM.Standard.A1.Flex"
  fault_domain        = var.fault_domain

  # Sized so normal use stays above Oracle's 20% idle-memory threshold.
  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_gbs
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_gbs
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = false
    hostname_label   = "fetchall"
  }

  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }

  lifecycle {
    ignore_changes = [source_details[0].source_id, metadata["user_data"]]
  }
}

data "oci_core_vnic_attachments" "fetchall" {
  compartment_id = var.tenancy_ocid
  instance_id    = oci_core_instance.fetchall.id
}

data "oci_core_private_ips" "fetchall" {
  vnic_id = data.oci_core_vnic_attachments.fetchall.vnic_attachments[0].vnic_id
}

resource "oci_core_public_ip" "fetchall" {
  compartment_id = var.tenancy_ocid
  lifetime       = "RESERVED"
  display_name   = "fetchall"
  private_ip_id  = data.oci_core_private_ips.fetchall.private_ips[0].id

  lifecycle {
    prevent_destroy = true
  }
}
