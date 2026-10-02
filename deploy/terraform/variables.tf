variable "tenancy_ocid" {
  type = string
}

variable "region" {
  type    = string
  default = "af-johannesburg-1"
}

variable "oci_profile" {
  type    = string
  default = "DEFAULT"
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/fetchall_oci.pub"
}

variable "ocpus" {
  type    = number
  default = 2
}

variable "memory_gbs" {
  type    = number
  default = 3
}

variable "boot_volume_gbs" {
  type    = number
  default = 50
}

variable "fault_domain" {
  type    = string
  default = null
}
